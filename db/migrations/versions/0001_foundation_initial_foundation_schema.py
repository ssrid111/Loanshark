"""initial foundation schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reviewed schema snapshot: no imports from changing application models.
    op.create_table(
        "communities",
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("guild_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_communities")),
        sa.UniqueConstraint(
            "platform", "guild_id", "channel_id", name=op.f("uq_communities_platform")
        ),
    )
    op.create_table(
        "users",
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_user_id", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("paused_lending", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("consent_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("consent_version >= 0", name=op.f("ck_users_valid_consent_version")),
        sa.CheckConstraint(
            "length(platform_user_id) > 0", name=op.f("ck_users_nonempty_platform_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("platform", "platform_user_id", name=op.f("uq_users_platform")),
    )
    op.create_table(
        "confirmations",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("resource_kind", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('APPROVED','DECLINED')", name=op.f("ck_confirmations_valid_decision")
        ),
        sa.CheckConstraint(
            (
                "(consumed_at IS NULL AND decision IS NULL) OR (consumed_at IS NOT NULL A"
                "ND decision IS NOT NULL)"
            ),
            name=op.f("ck_confirmations_decision_consumption"),
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at <= expires_at)",
            name=op.f("ck_confirmations_consumed_within_window"),
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_confirmations_valid_expiry")),
        sa.CheckConstraint(
            "resource_version > 0", name=op.f("ck_confirmations_positive_resource_version")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["users.id"], name=op.f("fk_confirmations_subject_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmations")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_confirmations_token_digest")),
    )
    op.create_index(
        op.f("ix_confirmations_expires_at"), "confirmations", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_confirmations_resource", "confirmations", ["resource_kind", "resource_id"], unique=False
    )
    op.create_index(
        op.f("ix_confirmations_subject_id"), "confirmations", ["subject_id"], unique=False
    )
    op.create_table(
        "found_reports",
        sa.Column("public_description", sa.String(length=500), nullable=False),
        sa.Column("encrypted_hidden_details", sa.LargeBinary(), nullable=False),
        sa.Column("verification_prompt", sa.String(length=200), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("community_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_item", sa.String(length=100), nullable=False),
        sa.Column("zone", sa.String(length=100), nullable=False),
        sa.Column("seen_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','RESOLVED','CANCELLED')", name=op.f("ck_found_reports_valid_status")
        ),
        sa.CheckConstraint(
            "seen_until >= seen_from", name=op.f("ck_found_reports_valid_time_window")
        ),
        sa.ForeignKeyConstraint(
            ["community_id"],
            ["communities.id"],
            name=op.f("fk_found_reports_community_id_communities"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"], ["users.id"], name=op.f("fk_found_reports_reporter_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_found_reports")),
    )
    op.create_index(
        op.f("ix_found_reports_community_id"), "found_reports", ["community_id"], unique=False
    )
    op.create_index(
        "ix_found_reports_match",
        "found_reports",
        ["canonical_item", "zone", "seen_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_found_reports_reporter_id"), "found_reports", ["reporter_id"], unique=False
    )
    op.create_table(
        "lending_policies",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("same_day_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "known_contacts_only", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("max_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "max_duration_minutes > 0", name=op.f("ck_lending_policies_positive_duration")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_lending_policies_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lending_policies")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_lending_policies_id")),
    )
    op.create_index(
        op.f("ix_lending_policies_owner_id"), "lending_policies", ["owner_id"], unique=False
    )
    op.create_table(
        "lost_reports",
        sa.Column("encrypted_identifying_details", sa.LargeBinary(), nullable=True),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("community_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_item", sa.String(length=100), nullable=False),
        sa.Column("zone", sa.String(length=100), nullable=False),
        sa.Column("seen_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','RESOLVED','CANCELLED')", name=op.f("ck_lost_reports_valid_status")
        ),
        sa.CheckConstraint(
            "seen_until >= seen_from", name=op.f("ck_lost_reports_valid_time_window")
        ),
        sa.ForeignKeyConstraint(
            ["community_id"],
            ["communities.id"],
            name=op.f("fk_lost_reports_community_id_communities"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"], ["users.id"], name=op.f("fk_lost_reports_reporter_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lost_reports")),
    )
    op.create_index(
        op.f("ix_lost_reports_community_id"), "lost_reports", ["community_id"], unique=False
    )
    op.create_index(
        "ix_lost_reports_match",
        "lost_reports",
        ["canonical_item", "zone", "seen_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lost_reports_reporter_id"), "lost_reports", ["reporter_id"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("resource_kind", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("before_state", sa.String(length=32), nullable=True),
        sa.Column("after_state", sa.String(length=32), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_log_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["confirmation_id"],
            ["confirmations.id"],
            name=op.f("fk_audit_log_confirmation_id_confirmations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"], unique=False)
    op.create_index(
        op.f("ix_audit_log_correlation_id"), "audit_log", ["correlation_id"], unique=False
    )
    op.create_index(
        "ix_audit_log_resource", "audit_log", ["resource_kind", "resource_id"], unique=False
    )
    op.create_table(
        "inventory",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_item", sa.String(length=100), nullable=False),
        sa.Column("subtype", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(canonical_item) > 0", name=op.f("ck_inventory_nonempty_item")),
        sa.CheckConstraint("version > 0", name=op.f("ck_inventory_positive_version")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_inventory_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "owner_id"],
            ["lending_policies.id", "lending_policies.owner_id"],
            name=op.f("fk_inventory_policy_id_lending_policies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_inventory_id")),
    )
    op.create_index(op.f("ix_inventory_owner_id"), "inventory", ["owner_id"], unique=False)
    op.create_index(op.f("ix_inventory_policy_id"), "inventory", ["policy_id"], unique=False)
    op.create_table(
        "requests",
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("community_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_item", sa.String(length=100), nullable=False),
        sa.Column("subtype", sa.String(length=100), nullable=True),
        sa.Column("need_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_return_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_zone", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="DRAFT", nullable=False),
        sa.Column("scope_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("scope_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "status IN ('DRAFT','AWAITING_SCOPE_CONFIRMATION','OPEN','RESERVED','FULF"
                "ILLED','CANCELLED','EXPIRED','UNMATCHED')"
            ),
            name=op.f("ck_requests_valid_status"),
        ),
        sa.CheckConstraint(
            "proposed_return_at > need_by", name=op.f("ck_requests_return_after_need")
        ),
        sa.CheckConstraint("scope_version > 0", name=op.f("ck_requests_positive_scope_version")),
        sa.ForeignKeyConstraint(
            ["borrower_id"], ["users.id"], name=op.f("fk_requests_borrower_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["community_id"], ["communities.id"], name=op.f("fk_requests_community_id_communities")
        ),
        sa.ForeignKeyConstraint(
            ["scope_confirmation_id"],
            ["confirmations.id"],
            name=op.f("fk_requests_scope_confirmation_id_confirmations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
    )
    op.create_index(op.f("ix_requests_borrower_id"), "requests", ["borrower_id"], unique=False)
    op.create_index(op.f("ix_requests_community_id"), "requests", ["community_id"], unique=False)
    op.create_index("ix_requests_status_need_by", "requests", ["status", "need_by"], unique=False)
    op.create_table(
        "offers",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING_OWNER", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            (
                "status IN ('PENDING_OWNER','OWNER_ACCEPTED','AWAITING_BORROWER','RESERVE"
                "D','DECLINED','EXPIRED','WITHDRAWN','RELEASED')"
            ),
            name=op.f("ck_offers_valid_status"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_offers_positive_version")),
        sa.ForeignKeyConstraint(
            ["item_id", "lender_id"],
            ["inventory.id", "inventory.owner_id"],
            name=op.f("fk_offers_item_id_inventory"),
        ),
        sa.ForeignKeyConstraint(
            ["lender_id"], ["users.id"], name=op.f("fk_offers_lender_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_offers_request_id_requests")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offers")),
        sa.UniqueConstraint("id", "request_id", "item_id", name=op.f("uq_offers_id")),
    )
    op.create_index(op.f("ix_offers_item_id"), "offers", ["item_id"], unique=False)
    op.create_index(op.f("ix_offers_lender_id"), "offers", ["lender_id"], unique=False)
    op.create_index(op.f("ix_offers_request_id"), "offers", ["request_id"], unique=False)
    op.create_table(
        "reservations",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "held_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("hold_expires_at > held_at", name=op.f("ck_reservations_positive_hold")),
        sa.CheckConstraint(
            "released_at IS NULL OR released_at >= held_at",
            name=op.f("ck_reservations_valid_release"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory.id"], name=op.f("fk_reservations_item_id_inventory")
        ),
        sa.ForeignKeyConstraint(
            ["offer_id", "request_id", "item_id"],
            ["offers.id", "offers.request_id", "offers.item_id"],
            name=op.f("fk_reservations_offer_id_offers"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_reservations_request_id_requests")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("id", "item_id", name=op.f("uq_reservations_id")),
        sa.UniqueConstraint("offer_id", name=op.f("uq_reservations_offer_id")),
    )
    op.create_index(op.f("ix_reservations_item_id"), "reservations", ["item_id"], unique=False)
    op.create_index(
        op.f("ix_reservations_request_id"), "reservations", ["request_id"], unique=False
    )
    op.create_index(
        "uq_active_reservation_item",
        "reservations",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index(
        "uq_active_reservation_request",
        "reservations",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_table(
        "loans",
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
        sa.Column("lender_return_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            (
                "(status = 'CLOSED' AND closed_at IS NOT NULL AND lender_return_confirmat"
                "ion_id IS NOT NULL) OR (status <> 'CLOSED' AND closed_at IS NULL)"
            ),
            name=op.f("ck_loans_closed_requires_receipt"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','RETURN_REPORTED','CLOSED')", name=op.f("ck_loans_valid_status")
        ),
        sa.CheckConstraint("borrower_id <> lender_id", name=op.f("ck_loans_distinct_participants")),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= start_at", name=op.f("ck_loans_valid_close_time")
        ),
        sa.CheckConstraint("due_at > start_at", name=op.f("ck_loans_positive_duration")),
        sa.ForeignKeyConstraint(
            ["borrower_id"], ["users.id"], name=op.f("fk_loans_borrower_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["item_id", "lender_id"],
            ["inventory.id", "inventory.owner_id"],
            name=op.f("fk_loans_item_id_inventory"),
        ),
        sa.ForeignKeyConstraint(["lender_id"], ["users.id"], name=op.f("fk_loans_lender_id_users")),
        sa.ForeignKeyConstraint(
            ["lender_return_confirmation_id"],
            ["confirmations.id"],
            name=op.f("fk_loans_lender_return_confirmation_id_confirmations"),
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id", "item_id"],
            ["reservations.id", "reservations.item_id"],
            name=op.f("fk_loans_reservation_id_reservations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loans")),
        sa.UniqueConstraint("reservation_id", name=op.f("uq_loans_reservation_id")),
    )
    op.create_index(op.f("ix_loans_borrower_id"), "loans", ["borrower_id"], unique=False)
    op.create_index(op.f("ix_loans_item_id"), "loans", ["item_id"], unique=False)
    op.create_index(op.f("ix_loans_lender_id"), "loans", ["lender_id"], unique=False)
    op.create_index("ix_loans_status_due_at", "loans", ["status", "due_at"], unique=False)

    op.execute("""
        CREATE FUNCTION reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = '42501';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_log_no_mutation
        BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation()
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'loanshark_runtime') THEN
                GRANT USAGE ON SCHEMA public TO loanshark_runtime;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
                    TO loanshark_runtime;
                REVOKE ALL ON audit_log FROM loanshark_runtime;
                GRANT SELECT, INSERT ON audit_log TO loanshark_runtime;
                REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM loanshark_runtime;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_mutation ON audit_log")
    op.execute("DROP FUNCTION reject_audit_mutation()")
    # Reviewed schema snapshot: no imports from changing application models.
    op.drop_index("ix_loans_status_due_at", table_name="loans")
    op.drop_index(op.f("ix_loans_lender_id"), table_name="loans")
    op.drop_index(op.f("ix_loans_item_id"), table_name="loans")
    op.drop_index(op.f("ix_loans_borrower_id"), table_name="loans")
    op.drop_table("loans")
    op.drop_index(
        "uq_active_reservation_request",
        table_name="reservations",
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.drop_index(
        "uq_active_reservation_item",
        table_name="reservations",
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.drop_index(op.f("ix_reservations_request_id"), table_name="reservations")
    op.drop_index(op.f("ix_reservations_item_id"), table_name="reservations")
    op.drop_table("reservations")
    op.drop_index(op.f("ix_offers_request_id"), table_name="offers")
    op.drop_index(op.f("ix_offers_lender_id"), table_name="offers")
    op.drop_index(op.f("ix_offers_item_id"), table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_requests_status_need_by", table_name="requests")
    op.drop_index(op.f("ix_requests_community_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_borrower_id"), table_name="requests")
    op.drop_table("requests")
    op.drop_index(op.f("ix_inventory_policy_id"), table_name="inventory")
    op.drop_index(op.f("ix_inventory_owner_id"), table_name="inventory")
    op.drop_table("inventory")
    op.drop_index("ix_audit_log_resource", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_correlation_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_lost_reports_reporter_id"), table_name="lost_reports")
    op.drop_index("ix_lost_reports_match", table_name="lost_reports")
    op.drop_index(op.f("ix_lost_reports_community_id"), table_name="lost_reports")
    op.drop_table("lost_reports")
    op.drop_index(op.f("ix_lending_policies_owner_id"), table_name="lending_policies")
    op.drop_table("lending_policies")
    op.drop_index(op.f("ix_found_reports_reporter_id"), table_name="found_reports")
    op.drop_index("ix_found_reports_match", table_name="found_reports")
    op.drop_index(op.f("ix_found_reports_community_id"), table_name="found_reports")
    op.drop_table("found_reports")
    op.drop_index(op.f("ix_confirmations_subject_id"), table_name="confirmations")
    op.drop_index("ix_confirmations_resource", table_name="confirmations")
    op.drop_index(op.f("ix_confirmations_expires_at"), table_name="confirmations")
    op.drop_table("confirmations")
    op.drop_table("users")
    op.drop_table("communities")
    # ### end Alembic commands ###
