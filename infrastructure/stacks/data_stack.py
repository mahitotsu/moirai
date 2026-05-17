from __future__ import annotations

import aws_cdk as cdk
import aws_cdk.aws_dynamodb as dynamodb
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------------------------------------------------------------------------
        # Tickets table — incident System of Record
        #
        # Access patterns:
        #   - Get ticket by ID              → PK lookup
        #   - List tickets by status        → status-created_at-index
        #   - List tickets by category      → category-created_at-index
        #   - Diagnosis Agent: past resolved tickets in same category
        #                                   → category-created_at-index + filter status=resolved
        #
        # Item shape (all string unless noted):
        #   ticket_id, status, severity, category, title, description,
        #   resolution?, created_at (ISO-8601), updated_at, resolved_at?
        # -------------------------------------------------------------------------
        self.tickets_table = dynamodb.Table(
            self,
            "TicketsTable",
            table_name="agora-tickets",
            partition_key=dynamodb.Attribute(
                name="ticket_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            # Enable Streams now — V3 Lambda consumer triggers on CREATED / RESOLVED
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
        )

        # List tickets by status ordered by creation time (UI Tickets tab, triage queries)
        self.tickets_table.add_global_secondary_index(
            index_name="status-created_at-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        # List tickets by category ordered by creation time (Diagnosis Agent similarity search)
        self.tickets_table.add_global_secondary_index(
            index_name="category-created_at-index",
            partition_key=dynamodb.Attribute(
                name="category",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        # -------------------------------------------------------------------------
        # Assets table — configuration management DB
        #
        # Access patterns:
        #   - Get asset by ID               → PK lookup
        #   - List assets by type           → type-name-index
        #   - List assets by environment    → environment-type-index
        #
        # Item shape (all string unless noted):
        #   asset_id, name, type, environment, status, description?,
        #   metadata? (Map), created_at (ISO-8601), updated_at
        # -------------------------------------------------------------------------
        self.assets_table = dynamodb.Table(
            self,
            "AssetsTable",
            table_name="agora-assets",
            partition_key=dynamodb.Attribute(
                name="asset_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # List assets by type ordered by name (Asset Service browsing)
        self.assets_table.add_global_secondary_index(
            index_name="type-name-index",
            partition_key=dynamodb.Attribute(
                name="type",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="name",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        # List assets by environment ordered by type (Resolution Agent context lookup)
        self.assets_table.add_global_secondary_index(
            index_name="environment-type-index",
            partition_key=dynamodb.Attribute(
                name="environment",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="type",
                type=dynamodb.AttributeType.STRING,
            ),
        )

