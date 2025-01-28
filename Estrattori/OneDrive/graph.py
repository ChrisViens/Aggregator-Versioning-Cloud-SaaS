# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# <UserAuthConfigSnippet>
from configparser import SectionProxy
from azure.identity import DeviceCodeCredential
from msgraph import GraphServiceClient
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder)
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import (
    SendMailPostRequestBody)
from msgraph.generated.models.message import Message
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from azure.identity import DeviceCodeCredential
from msgraph import GraphServiceClient

class Graph:
    def __init__(self, config, credential=None):
        self.settings = config
        client_id = self.settings['clientId']
        tenant_id = self.settings.get('tenantId', 'consumers')  # Default a 'consumers'
        graph_scopes = self.settings['graphUserScopes'].split(' ')

        # Usa un credential esistente o creane uno nuovo
        self.device_code_credential = credential or DeviceCodeCredential(client_id=client_id, tenant_id=tenant_id)
        self.user_client = GraphServiceClient(self.device_code_credential, scopes=graph_scopes)


    async def get_user_token(self):
        """Ottieni un token utente."""
        graph_scopes = self.settings['graphUserScopes']
        access_token = self.device_code_credential.get_token(graph_scopes)
        return access_token.token

    async def get_user(self):
        """Ottieni informazioni sull'utente autenticato."""
        user = await self.user_client.me.get()
        return user