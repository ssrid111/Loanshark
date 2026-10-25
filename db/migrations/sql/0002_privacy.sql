CREATE SCHEMA private;
-- statement
REVOKE ALL ON SCHEMA private FROM PUBLIC;
-- statement
CREATE FUNCTION private.current_student() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT u.id FROM public.api_tokens t JOIN public.users u ON u.id=t.user_id
    WHERE t.token_digest=encode(sha256(convert_to(
        coalesce(current_setting('loanshark.token', true), ''), 'UTF8')), 'hex')
      AND t.revoked_at IS NULL AND t.expires_at > statement_timestamp()
      AND u.inactive_at IS NULL
$$;
-- statement
CREATE FUNCTION private.current_token_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT t.id FROM public.api_tokens t JOIN public.users u ON u.id=t.user_id
    WHERE t.token_digest=encode(sha256(convert_to(
        coalesce(current_setting('loanshark.token', true), ''), 'UTF8')), 'hex')
      AND t.revoked_at IS NULL AND t.expires_at > statement_timestamp()
      AND u.inactive_at IS NULL
$$;
-- statement
CREATE FUNCTION private.record_owner_denial(correlation uuid) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    INSERT INTO public.audit_log(id, event_type, actor_id, resource_kind, resource_id,
                                 correlation_id, created_at)
    VALUES(gen_random_uuid(), 'owner_operation_denied', private.current_student(),
           'authorization', gen_random_uuid(), correlation, statement_timestamp())
$$;
-- statement
CREATE FUNCTION private.authenticate(correlation uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE actor uuid;
BEGIN
    actor := private.current_student();
    IF actor IS NULL THEN PERFORM private.record_owner_denial(correlation); END IF;
    RETURN actor;
END $$;
-- statement
CREATE FUNCTION private.add_trusted_contact(contact uuid, community uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE actor uuid;
BEGIN
    actor := private.current_student();
    IF actor IS NULL OR actor=contact OR (SELECT count(*) FROM public.memberships m
        JOIN public.users u ON u.id=m.user_id AND u.inactive_at IS NULL
        WHERE m.community_id=community AND m.user_id IN (actor,contact)
        AND m.verified AND m.opted_in) <> 2 THEN
        RAISE EXCEPTION 'Not authorized' USING ERRCODE='42501';
    END IF;
    INSERT INTO public.trusted_contacts(id,owner_id,contact_id,community_id)
    VALUES(gen_random_uuid(),actor,contact,community)
    ON CONFLICT (owner_id,contact_id,community_id) DO NOTHING;
END $$;
-- statement
DO $$
DECLARE target text; owner_column text;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='loanshark_runtime') OR
       NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='loanshark_gateway') THEN
        RAISE EXCEPTION 'Run bootstrap_db.py before applying privacy migration';
    END IF;
    -- Neither login is a table owner, superuser, role administrator, or BYPASSRLS role.
    GRANT USAGE ON SCHEMA private TO loanshark_runtime,loanshark_gateway;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA private FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION private.current_student(),private.current_token_id(),private.authenticate(uuid),
        private.record_owner_denial(uuid),private.add_trusted_contact(uuid,uuid)
        TO loanshark_runtime;
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM loanshark_runtime;
    GRANT SELECT ON alembic_version,communities,handoff_locations TO loanshark_runtime;
    GRANT SELECT ON users TO loanshark_runtime;
    GRANT UPDATE(paused_lending,schedule_known_from,schedule_known_until,schedule_verified_at)
        ON users TO loanshark_runtime;
    GRANT SELECT,INSERT,UPDATE,DELETE ON inventory,lending_policies,schedule_blocks,
        availability_windows,trusted_contacts,sharing_approvals TO loanshark_runtime;
    GRANT SELECT ON memberships TO loanshark_runtime;
    GRANT UPDATE(opted_in) ON memberships TO loanshark_runtime;
    GRANT SELECT,INSERT ON coordination_grants TO loanshark_runtime;
    GRANT UPDATE(revoked_at) ON coordination_grants TO loanshark_runtime;
    GRANT SELECT,INSERT ON audit_log TO loanshark_runtime;
    -- Gateway has no general-purpose table reads, and no membership in runtime/migration roles.
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM loanshark_gateway;
    REVOKE CREATE ON SCHEMA public FROM loanshark_runtime,loanshark_gateway;
    FOREACH target IN ARRAY ARRAY['users','inventory','lending_policies','schedule_blocks',
        'availability_windows','trusted_contacts','memberships','audit_log'] LOOP
        owner_column := CASE target WHEN 'users' THEN 'id' WHEN 'memberships' THEN 'user_id'
                             WHEN 'audit_log' THEN 'actor_id' ELSE 'owner_id' END;
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',target);
        EXECUTE format('CREATE POLICY owner_only ON public.%I TO loanshark_runtime '
                       'USING (%I=private.current_student()) '
                       'WITH CHECK (%I=private.current_student())',target,owner_column,owner_column);
    END LOOP;
    ALTER TABLE public.coordination_grants ENABLE ROW LEVEL SECURITY;
    CREATE POLICY grant_read ON public.coordination_grants FOR SELECT TO loanshark_runtime
        USING (requester_id=private.current_student() OR target_owner_id=private.current_student());
    CREATE POLICY grant_insert ON public.coordination_grants FOR INSERT TO loanshark_runtime
        WITH CHECK (requester_id=private.current_student()
                    AND authorizing_token_id=private.current_token_id());
    CREATE POLICY grant_revoke ON public.coordination_grants FOR UPDATE TO loanshark_runtime
        USING (requester_id=private.current_student() OR target_owner_id=private.current_student())
        WITH CHECK (requester_id=private.current_student() OR target_owner_id=private.current_student());
    ALTER TABLE public.sharing_approvals ENABLE ROW LEVEL SECURITY;
    CREATE POLICY sharing_owner ON public.sharing_approvals TO loanshark_runtime
        USING (owner_id=private.current_student())
        WITH CHECK (owner_id=private.current_student() AND EXISTS (
            SELECT 1 FROM public.coordination_grants g WHERE g.id=grant_id
            AND g.target_owner_id=private.current_student() AND g.revoked_at IS NULL));
END $$;
-- statement
CREATE FUNCTION private.check_availability(capability text, evaluated_at timestamptz, correlation uuid)
RETURNS TABLE(eligible boolean,location text,window_start timestamptz,window_end timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    q public.coordination_grants%ROWTYPE;
    owner_row public.users%ROWTYPE;
    borrower_row public.users%ROWTYPE;
    meeting public.handoff_locations%ROWTYPE;
    item_policy record;
    slots record;
    candidate timestamptz;
    min_handoff interval := interval '5 minutes';
    resource uuid := gen_random_uuid();
BEGIN
    eligible := false; location := NULL; window_start := NULL; window_end := NULL;
    <<evaluate>> BEGIN
        SELECT * INTO q FROM public.coordination_grants g
        WHERE g.capability_digest=encode(sha256(convert_to(capability,'UTF8')),'hex') FOR UPDATE;
        IF NOT FOUND THEN EXIT evaluate; END IF;
        resource := q.id;
        IF NOT EXISTS(SELECT 1 FROM public.api_tokens t WHERE t.id=q.authorizing_token_id
            AND t.user_id=q.requester_id AND t.revoked_at IS NULL
            AND t.expires_at>statement_timestamp()) THEN EXIT evaluate; END IF;
        IF q.revoked_at IS NOT NULL OR q.expires_at <= evaluated_at OR
           q.window_end <= evaluated_at OR q.check_count >= 20 THEN EXIT evaluate; END IF;
        UPDATE public.coordination_grants SET check_count=check_count+1 WHERE id=q.id;
        -- Membership and opt-in are always revalidated, including after consent was issued.
        IF (SELECT count(*) FROM public.memberships m WHERE m.community_id=q.community_id
            AND m.user_id IN(q.requester_id,q.target_owner_id)
            AND m.verified AND m.opted_in) <> 2 THEN EXIT evaluate; END IF;
        SELECT * INTO owner_row FROM public.users WHERE id=q.target_owner_id;
        SELECT * INTO borrower_row FROM public.users WHERE id=q.requester_id;
        IF owner_row.inactive_at IS NOT NULL OR borrower_row.inactive_at IS NOT NULL OR
           owner_row.paused_lending THEN EXIT evaluate; END IF;
        IF owner_row.schedule_known_from IS NULL OR owner_row.schedule_known_until IS NULL OR
           borrower_row.schedule_known_from IS NULL OR borrower_row.schedule_known_until IS NULL OR
           owner_row.schedule_verified_at IS NULL OR borrower_row.schedule_verified_at IS NULL OR
           owner_row.schedule_verified_at < evaluated_at-interval '24 hours' OR
           borrower_row.schedule_verified_at < evaluated_at-interval '24 hours' OR
           owner_row.schedule_verified_at > evaluated_at OR
           borrower_row.schedule_verified_at > evaluated_at OR
           owner_row.schedule_known_from > q.window_start OR
           borrower_row.schedule_known_from > q.window_start OR
           owner_row.schedule_known_until < q.window_end OR
           borrower_row.schedule_known_until < q.window_end THEN EXIT evaluate; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=owner_row.timezone)
            THEN EXIT evaluate; END IF;
        SELECT * INTO meeting FROM public.handoff_locations l
            WHERE l.id=q.location_id AND l.community_id=q.community_id AND l.approved;
        IF NOT FOUND THEN EXIT evaluate; END IF;
        FOR item_policy IN
            SELECT i.id,p.same_day_only,p.max_duration_minutes FROM public.inventory i
            JOIN public.lending_policies p ON p.id=i.policy_id AND p.owner_id=i.owner_id
            WHERE i.owner_id=q.target_owner_id AND i.active
            AND i.canonical_item=q.canonical_item AND (q.subtype IS NULL OR i.subtype=q.subtype)
            AND (NOT p.known_contacts_only OR EXISTS (
                SELECT 1 FROM public.trusted_contacts c WHERE c.owner_id=i.owner_id
                AND c.contact_id=q.requester_id AND c.community_id=q.community_id))
            AND NOT EXISTS(SELECT 1 FROM public.reservations r
                           WHERE r.item_id=i.id AND r.released_at IS NULL)
            ORDER BY i.id
        LOOP
            FOR slots IN
                SELECT greatest(a.start_at,b.start_at,q.window_start,evaluated_at) AS starts,
                       least(a.end_at,b.end_at,q.window_end) AS ends,
                       make_interval(mins=>a.travel_buffer_minutes) AS owner_buffer,
                       make_interval(mins=>b.travel_buffer_minutes) AS borrower_buffer
                FROM public.availability_windows a CROSS JOIN public.availability_windows b
                WHERE a.owner_id=q.target_owner_id AND b.owner_id=q.requester_id
                AND a.location_id=q.location_id AND b.location_id=q.location_id
                ORDER BY starts,ends
            LOOP
                IF slots.ends-slots.starts < min_handoff THEN CONTINUE; END IF;
                -- Candidate starts include ends of busy blocks so a partially busy window can fit.
                FOR candidate IN
                    SELECT DISTINCT possible FROM (
                        SELECT slots.starts AS possible
                        UNION ALL SELECT s.end_at+slots.owner_buffer FROM public.schedule_blocks s
                            WHERE s.owner_id=q.target_owner_id
                        UNION ALL SELECT s.end_at+slots.borrower_buffer FROM public.schedule_blocks s
                            WHERE s.owner_id=q.requester_id
                    ) choices WHERE possible>=slots.starts AND possible+min_handoff<=slots.ends
                    ORDER BY possible
                LOOP
                    IF q.return_at-candidate > make_interval(mins=>item_policy.max_duration_minutes)
                        THEN CONTINUE; END IF;
                    IF item_policy.same_day_only AND
                        (q.return_at AT TIME ZONE owner_row.timezone)::date <>
                        (candidate AT TIME ZONE owner_row.timezone)::date THEN CONTINUE; END IF;
                    IF EXISTS(SELECT 1 FROM public.schedule_blocks s WHERE
                        (s.owner_id=q.target_owner_id AND
                         s.start_at-slots.owner_buffer<candidate+min_handoff AND
                         s.end_at+slots.owner_buffer>candidate) OR
                        (s.owner_id=q.requester_id AND
                         s.start_at-slots.borrower_buffer<candidate+min_handoff AND
                         s.end_at+slots.borrower_buffer>candidate)) THEN CONTINUE; END IF;
                    eligible := true;
                    -- No place/time disclosure until this owner explicitly approves these exact terms.
                    IF EXISTS(SELECT 1 FROM public.sharing_approvals a WHERE a.grant_id=q.id
                              AND a.owner_id=q.target_owner_id) THEN
                        location := meeting.code;
                        window_start := candidate;
                        window_end := candidate+min_handoff;
                    END IF;
                    EXIT evaluate;
                END LOOP;
            END LOOP;
        END LOOP;
    END evaluate;
    INSERT INTO public.audit_log(id,event_type,resource_kind,resource_id,correlation_id,created_at)
    VALUES(gen_random_uuid(),CASE WHEN eligible THEN 'availability_eligible'
                                ELSE 'availability_ineligible' END,
           'coordination_grant',resource,correlation,statement_timestamp());
    RETURN NEXT;
END $$;
-- statement
REVOKE ALL ON FUNCTION private.check_availability(text,timestamptz,uuid) FROM PUBLIC;
-- statement
GRANT EXECUTE ON FUNCTION private.check_availability(text,timestamptz,uuid) TO loanshark_gateway;
