"""Strawberry GraphQL schema assembly."""
import strawberry
from strawberry.fastapi import GraphQLRouter

from auth_service.presentation.graphql.mutations import AuthMutation
from auth_service.presentation.graphql.queries import AuthQuery


schema = strawberry.Schema(query=AuthQuery, mutation=AuthMutation)


def create_graphql_router(get_context) -> GraphQLRouter:
    return GraphQLRouter(schema, context_getter=get_context)
