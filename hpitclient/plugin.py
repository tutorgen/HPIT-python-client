import time

from .message_sender_mixin import MessageSenderMixin
from .exceptions import PluginPollError, BadCallbackException
from .exceptions import AuthenticationError, InvalidParametersError, AuthorizationError

import json

class Plugin(MessageSenderMixin):
    def __init__(self, entity_id, api_key, wildcard_callback=None):
        super().__init__()

        self.run_loop = True
        self.entity_id = str(entity_id)
        self.api_key = str(api_key)
        self.wildcard_callback = wildcard_callback
        self.transaction_callback = None
        self.callbacks = {}

        self.poll_wait = 1500

        self._add_hooks(
            'pre_poll_messages', 'post_poll_messages', 
            'pre_dispatch_messages', 'post_dispatch_messages', 
            'pre_handle_transactions', 'post_handle_transcations')


    def post_connect(self):
        pass


    def register_transaction_callback(self,callback):
        """
        Set a callback for transactions and start listening for them.
        """
        if not hasattr(callback,"__call__"):
            raise BadCallbackException("The callback submitted is not callable.")
        self._post_data('plugin/subscribe', {'message_name' : "transaction"})
        self.transaction_callback = callback
        
        
    def clear_transaction_callback(self):
        """
        Clear the callback for transactions and stop listening for them.
        """
        self._post_data('plugin/unsubscribe', {'message_name': "transaction"})
        self.transaction_callback = None
        

    def list_subscriptions(self):
        """
        Polls the HPIT server for a list of message names we currently subscribing to.
        """
        subscriptions = self._get_data('plugin/subscription/list')['subscriptions']

        for sub in subscriptions:
            if sub not in self.callbacks:
                self.callbacks[sub] = None

        return self.callbacks


    def subscribe(self, messages):
        """
        Subscribe to messages, each argument is exepcted as a key value pair where
        the key is the message's name and the value is the callback function.
        """
        for message_name, callback in messages.items():
            self._post_data('plugin/subscribe', {'message_name' : message_name})
            self.callbacks[message_name] = callback
            

    def unsubscribe(self, *message_names):
        """
        Unsubscribe from messages. Pass each message name as a separate parameter.
        """
        for message_name in message_names:
            if message_name in self.callbacks:
                self._post_data('plugin/unsubscribe', {'message_name': message_name})
                del self.callbacks[message_name]


    #Plugin Only
    def share_message(self, message_name, other_entity_ids):
        """
        Sends a blocking request to the HPIT server to share your 
        message type with other plugins. This request is NOT asyncronous.

        Input:
            message_name - The name of the message to share.
            other_entity_ids - Other plugins that you are authorizing to listen to
            this message.

        Returns: 
            True - Everything went well and the authorization request was granted.

        Throws:
            AuthenticationError - This entity is not signed into HPIT.
            InvalidParametersError - The message_name or other_entity_ids is invalid or empty.
            AuthorizationError - This entity is not the owner of this message.
        """
        if not message_name:
            raise InvalidParametersError('message_name is empty or None')

        if not other_entity_ids:
            raise InvalidParametersError('other_entity_ids is empty or None')

        if not isinstance(message_name, str):
            raise InvalidParametersError('message_name must be a string')

        if not isinstance(other_entity_ids, str) and not isinstance(other_entity_ids, list):
            raise InvalidParametersError('other_entity_ids must be a string or a list')

        response = self._post_data('share-message', {
            'message_name': message_name,
            'other_entity_ids': other_entity_ids
        })

        if 'error' in response and response['error'] == 'not owner':
            raise AuthorizationError('This entity is not the owner of this message.')

        #Bad responses will cause an exception. We can safely just return true.
        return True


    #Plugin Only
    def secure_resource(self, owner_id):
        """
        Sends a blocking request to the HPIT server to create a new resource authorization
        token. When you return the resource_id generated in this request to HPIT in future 
        responses to message queries, HPIT will lock down the response and refuse to send
        it onto entities that you haven't authorized to view this specific token.

        Input:
            owner_id - The entity that owns this resource. The plugin here isn't the "owner"
            of this resource. The entity that sent this request to this plugin is the "owner" 
            and you are giving them a key to their data.

        Returns:
            string - The resource authorization token from HPIT.
            False - Failed to secure the resource.

        Throws:
            AuthenticationError - This entity is not signed into HPIT.
            InvalidParametersError - The message_name or other_entity_ids is invalid or empty.
            AuthorizationError - This entity is not the owner of this message.
        """
        if not owner_id:
            raise InvalidParametersError('owner_id is empty or None')

        if not isinstance(owner_id, str):
            raise InvalidParametersError('owner_id must be a string')

        response = self._post_data('new-resource', {
            'owner_id': owner_id
        })

        if 'resource_id' in response.json():
            return response.json()['resource_id']

        return False


    def _poll(self):
        """
        Get a list of new messages from the server for messages we are listening 
        to.
        """
        return self._get_data('plugin/message/list')['messages']


    def _handle_transactions(self):
        """
        Get a list of datashop transactions from the server. 
        """
        
        """UNUSED, transactions now go with normal messagse
        
        transaction_data = self._get_data('plugin/transaction/list')['transactions']

        for item in transaction_data:
            payload = item["message"]
            
            #Inject the message_id into the payload
            payload['message_id'] = item['message_id']
            payload['sender_entity_id'] = item['sender_entity_id']
            payload['time_created'] = item['time_created']
            
            if self.transaction_callback:
                self.transaction_callback(payload)

        return True
        """

    def _dispatch(self, message_data):
        """
        For each message recieved route it to the appropriate callback.
        """
        if not self._try_hook('pre_dispatch_messages'):
            return False

        for message_item in message_data:
            message = message_item['message_name']
            payload = message_item['message']

            #Inject the message_id into the payload
            payload['message_id'] = message_item['message_id']
            payload['sender_entity_id'] = message_item['sender_entity_id']
            payload['time_created'] = message_item['time_created']

            if message == "transaction":
                if self.transaction_callback:
                    self.transaction_callback(payload)
            else:
                try:
                    self.callbacks[message](payload)
                except KeyError:
                    #No callback registered try the wildcard
                    if self.wildcard_callback:
                        try:
                            self.wildcard_callback(payload)
                        except TypeError:
                            raise PluginPollError("Wildcard Callback is not a callable")
                except TypeError as e:
                    #Callback isn't a function
                    if self.callbacks[message] is None:
                        raise PluginPollError("No callback registered for message: <" + message + ">")
                    else:
                        raise e

        if not self._try_hook('post_dispatch_messages'):
            return False

        return True


    def start(self):
        """
        Start the plugin. Connect to the HPIT server. Then being polling and dispatching
        message callbacks based on messages we subscribe to.
        """
        self.run_loop = True;
        self.connect()
        self.list_subscriptions()

        try:
            while self.run_loop:

                time.sleep(self.poll_wait/1000)

                #Handle messages submitted by tutors
                if not self._try_hook('pre_poll_messages'):
                    break;

                message_data = self._poll()

                if not self._try_hook('post_poll_messages'):
                    break;

                if not self._dispatch(message_data):
                    return False
                """UNUSED transactions now go with normal messages
                
                if not self._try_hook('pre_handle_transactions'):
                    break;

                if not self._handle_transactions():
                    return False

                if not self._try_hook('post_handle_transactions'):
                    break;
                """

                #Handle responses from other plugins
                responses = self._poll_responses()

                if not self._dispatch_responses(responses):
                    break;

        except KeyboardInterrupt:
            self.disconnect()
        except:
            self.disconnect()
            raise


    def stop(self):
        self.run_loop = False


    def send_response(self, message_id, payload):
        """
        Sends a response to HPIT upon handling a specific message.

        Responses are handled differently than normal messages as they are destined
        for a only the original sender of the message_id to recieve the response.
        """
        self._post_data('response', {
            'message_id': message_id,
            'payload': payload
        })
        
    def get_shared_messages(self,args):
        shared_messages = None
        if args: 
            self.args = json.loads(args[1:-1])
            try:
                shared_messages = self.args["shared_messages"]
            except (KeyError, TypeError):
                shared_messages = None
        else:
            shared_messages = None
        
        if isinstance(shared_messages,dict):
            for k,v in shared_messages.items():
                if not isinstance(v,str) and not isinstance(v,list):
                    shared_messages = None
                    break
                if not isinstance(k,str):
                    shared_messages = None
                    break
        else:
            shared_messages = None
        
        return shared_messages
