"""Definitions for MCP tools exposed by the Integration Hub."""

import uuid
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class ToolDefinition(TypedDict):
    description: str
    args_model: type[BaseModel]
    service: str
    method: str


class GmailSendArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Gmail credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    to: str = Field(..., description="Recipient email address.")
    subject: str = Field(..., description="Email subject.")
    body: str = Field("", description="Plain text body.")
    body_html: str | None = Field(None, description="Optional HTML body.")


class GmailListArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Gmail credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    query: str = Field(
        "is:unread", description="Gmail search query (e.g. 'is:unread', 'from:boss')."
    )
    max_results: int = Field(10, description="Maximum number of messages to return.")
    page_token: str | None = Field(
        None,
        description="Cursor from a previous response's ``next_page_token``. "
        "Omit for the first page.",
    )


class GmailReadArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Gmail credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    message_id: str = Field(..., description="The Gmail message ID to fetch.")


class GmailReplyArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Gmail credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    thread_id: str = Field(..., description="The Gmail thread ID to reply in.")
    to: str = Field(..., description="Recipient email address.")
    subject: str = Field(..., description="Email subject (will be prefixed with 'Re:' if missing).")
    body: str = Field("", description="Plain text reply body.")
    body_html: str | None = Field(None, description="Optional HTML reply body.")


class OutlookSendArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Outlook credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    to: str = Field(..., description="Recipient email address.")
    subject: str = Field(..., description="Email subject.")
    body: str = Field("", description="Plain text body.")


class OutlookListArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Outlook credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    folder: str = Field(
        "Inbox", description="Mailbox folder to read from (e.g. 'Inbox', 'SentItems')."
    )
    filter_query: str = Field(
        "isRead eq false", description="OData filter expression (e.g. 'isRead eq false')."
    )
    max_results: int = Field(10, description="Maximum number of messages to return.")
    page_token: str | None = Field(
        None,
        description="``@odata.nextLink`` URL from a previous response. Omit for the first page.",
    )


class OutlookReadArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Outlook credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    message_id: str = Field(..., description="The Outlook message ID to fetch.")


class OutlookReplyArgs(BaseModel):
    credential_id: uuid.UUID = Field(..., description="The ID of the Outlook credential to use.")
    company_id: uuid.UUID = Field(..., description="The ID of the company owning the credential.")
    message_id: str = Field(..., description="The Outlook message ID to reply to.")
    body: str = Field("", description="Plain text reply body.")
    body_html: str | None = Field(None, description="Optional HTML reply body.")


class DriveListArgs(BaseModel):
    company_id: uuid.UUID = Field(..., description="The ID of the company.")
    query: str | None = Field(None, description="Google Drive search query.")
    page_size: int = Field(20, description="Number of files to return.")


class StripeListInvoicesArgs(BaseModel):
    limit: int = Field(10, description="Maximum number of invoices to return.")


class StripeGetCustomerArgs(BaseModel):
    customer_id: str = Field(..., description="The ID of the Stripe customer to fetch.")


class DatadogQueryLogsArgs(BaseModel):
    query: str = Field(
        ..., description="Datadog log search query (e.g., 'service:backend status:error')."
    )
    time_from: str = Field("now-1h", description="Start time for query (e.g., 'now-1h', 'now-1d').")
    time_to: str = Field("now", description="End time for query.")
    limit: int = Field(10, description="Maximum number of logs to return.")


class ElasticsearchSearchArgs(BaseModel):
    index: str = Field(..., description="Elasticsearch index to search in.")
    query: str = Field(..., description="Query string for the search.")
    size: int = Field(10, description="Number of results to return.")


class PostgresDescribeTableArgs(BaseModel):
    table_name: str = Field(..., description="Name of the table to describe.")


class PostgresRunQueryArgs(BaseModel):
    sql_query: str = Field(
        ..., description="The SQL select query to execute. Limited to read-only queries."
    )
    company_id: uuid.UUID | None = Field(
        None,
        description=(
            "Tenant scope. Required for /ai-tools/run calls — injected "
            "automatically from the caller's JWT by the route. Absent in "
            "MCP stdio server calls (which have no per-tenant context)."
        ),
    )


class PostgresListTablesArgs(BaseModel):
    pass


# ── Notification rules — used by the Rule Builder agent ─────────────────────


class ListNotificationRulesArgs(BaseModel):
    company_id: uuid.UUID = Field(..., description="Tenant whose rules to list.")
    active_only: bool = Field(False, description="If True, return only enabled rules.")
    limit: int = Field(50, description="Max rows to return.")


class ListNotificationEventTypesArgs(BaseModel):
    company_id: uuid.UUID = Field(
        ...,
        description="Tenant whose event types to list. Each tenant owns "
        "its own ``notification_event_types`` entries.",
    )


class CreateNotificationRuleArgs(BaseModel):
    company_id: uuid.UUID = Field(..., description="Tenant the rule belongs to.")
    created_by: uuid.UUID = Field(..., description="User UUID stamping the rule.")
    name: str = Field(..., description="Human-readable rule name.")
    event_type_id: uuid.UUID = Field(
        ...,
        description="UUID of the event type this rule fires on. "
        "Use list_notification_event_types to discover the catalogue.",
    )
    channel_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Notification channels (email/sms/etc) to fan out to.",
    )
    template_id: uuid.UUID = Field(..., description="UUID of the message template to render.")
    recipient_strategy: str = Field(
        "all_users",
        description="One of: ``all_users``, ``role_based``, ``custom``. "
        "Determines who receives the notification.",
    )
    recipient_config: dict[str, Any] | None = Field(
        None,
        description="Strategy-specific config (e.g. ``{role_id: ...}`` for role_based).",
    )
    conditions: list[dict[str, Any]] | None = Field(
        None,
        description="Optional list of condition objects. Each condition is "
        "``{field, operator, value}``; the rule fires when all match.",
    )
    priority: int = Field(5, description="Lower = earlier in the dispatch order.")


# ── Inbound connectors — claims/FNOL gateway (claims-platform A4) ───────────


class ListInboundConnectorsArgs(BaseModel):
    pass


class IngestViaConnectorArgs(BaseModel):
    connector_key: str = Field(
        ...,
        description="Connector key (use list_inbound_connectors to discover), "
        "e.g. 'generic' or 'acme_fnol'.",
    )
    payload: dict[str, Any] = Field(..., description="The raw vendor FNOL/claim payload to ingest.")
    company_id: uuid.UUID | None = Field(
        None,
        description="Target contractor company the claim feeds into (forwarded "
        "downstream as X-Company-Id).",
    )


# Tool definitions for registration
TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "list_inbound_connectors": {
        "description": "List the configured inbound claim/FNOL connectors "
        "(the gateway that turns a carrier claim into a queued project).",
        "args_model": ListInboundConnectorsArgs,
        "service": "connector_service",
        "method": "list_connectors",
    },
    "ingest_via_connector": {
        "description": "Ingest a carrier/TPA FNOL through an inbound connector: "
        "publishes a canonical claim event and forwards it to the owning vertical "
        "app, which creates a pending project in the assignment queue.",
        "args_model": IngestViaConnectorArgs,
        "service": "connector_service",
        "method": "ingest",
    },
    "gmail_send": {
        "description": "Send an email using a Gmail account.",
        "args_model": GmailSendArgs,
        "service": "email_service",
        "method": "gmail_send",
    },
    "gmail_list": {
        "description": "List unread or filtered messages from a Gmail account.",
        "args_model": GmailListArgs,
        "service": "email_service",
        "method": "gmail_list_unread",
    },
    "gmail_read": {
        "description": "Read a single Gmail message in full (headers + body) by message ID.",
        "args_model": GmailReadArgs,
        "service": "email_service",
        "method": "gmail_get_message",
    },
    "gmail_reply": {
        "description": "Reply to an existing Gmail thread.",
        "args_model": GmailReplyArgs,
        "service": "email_service",
        "method": "gmail_reply",
    },
    "outlook_send": {
        "description": "Send an email using an Outlook/Microsoft 365 account.",
        "args_model": OutlookSendArgs,
        "service": "email_service",
        "method": "outlook_send",
    },
    "outlook_list": {
        "description": "List messages from an Outlook/Microsoft 365 mailbox folder.",
        "args_model": OutlookListArgs,
        "service": "email_service",
        "method": "outlook_list_messages",
    },
    "outlook_read": {
        "description": "Read a single Outlook message in full (headers + body) by message ID.",
        "args_model": OutlookReadArgs,
        "service": "email_service",
        "method": "outlook_get_message",
    },
    "outlook_reply": {
        "description": "Reply to an existing Outlook message.",
        "args_model": OutlookReplyArgs,
        "service": "email_service",
        "method": "outlook_reply",
    },
    "drive_list": {
        "description": "List files in a Google Drive account.",
        "args_model": DriveListArgs,
        "service": "google_drive_service",
        "method": "list_files",
    },
    "stripe_list_invoices": {
        "description": "List recent Stripe invoices.",
        "args_model": StripeListInvoicesArgs,
        "service": "stripe_service",
        "method": "list_invoices",
    },
    "stripe_get_customer": {
        "description": "Fetch details of a specific Stripe customer.",
        "args_model": StripeGetCustomerArgs,
        "service": "stripe_service",
        "method": "get_customer",
    },
    "datadog_query_logs": {
        "description": "Query logs from Datadog.",
        "args_model": DatadogQueryLogsArgs,
        "service": "observability_service",
        "method": "datadog_query_logs",
    },
    "elasticsearch_search": {
        "description": "Search an Elasticsearch index.",
        "args_model": ElasticsearchSearchArgs,
        "service": "observability_service",
        "method": "elasticsearch_search",
    },
    "postgres_list_tables": {
        "description": "List all tables in the Postgres public schema.",
        "args_model": PostgresListTablesArgs,
        "service": "postgres_service",
        "method": "list_tables",
    },
    "postgres_describe_table": {
        "description": "Retrieve the column names and data types of a specific table.",
        "args_model": PostgresDescribeTableArgs,
        "service": "postgres_service",
        "method": "describe_table",
    },
    "postgres_run_query": {
        "description": "Run a raw SQL query against Postgres. Only SELECT statements are permitted.",
        "args_model": PostgresRunQueryArgs,
        "service": "postgres_service",
        "method": "run_query",
    },
    # ── Notification rules — Rule Builder agent's toolset ────────────────
    "list_notification_rules": {
        "description": "List notification rules configured for a company.",
        "args_model": ListNotificationRulesArgs,
        "service": "rule_service",
        "method": "list_rules",
    },
    "list_notification_event_types": {
        "description": (
            "List the catalogue of event types (rule triggers) for a company. "
            "Use before create_notification_rule so the agent picks a real event_type_id."
        ),
        "args_model": ListNotificationEventTypesArgs,
        "service": "rule_service",
        "method": "list_event_types",
    },
    "create_notification_rule": {
        "description": (
            "Create a notification rule binding an event_type to one or more "
            "channels via a template, with optional conditions and "
            "recipient strategy."
        ),
        "args_model": CreateNotificationRuleArgs,
        "service": "rule_service",
        "method": "create_rule",
    },
}
