import time

from .message_sender_mixin import MessageSenderMixin
from .exceptions import ResponseDispatchError
from .exceptions import InvalidMessageNameException

class Tutor(MessageSenderMixin):
    def __init__(self, entity_id, api_key, callback, **kwargs):
        super().__init__()

        self.run_loop = True
        self.entity_id = str(entity_id)
        self.api_key = str(api_key)
        self.callback = callback

        self.poll_wait = 1500
        self.block_timeout_time = 10
        
        self.blocking_store = {}

        for k, v in kwargs.items():
            setattr(self, k, v)

    def send_blocking(self,message_name,payload):
        """
        This is a special variant of the send message that will halt a tutor until
        a response is received.  It will time out after a set amount of time.
        """
        
        def get_blocking_callback(message_id):
            def blocking_callback(response):
                self.blocking_store[message_id] = response
            
            self.blocking_store[message_id] = None
            return blocking_callback
        
        if message_name == "transaction":
            raise InvalidMessageNameException("Cannot use message_name 'transaction'.  Use send_transaction() method for datashop transactions.")
            
        response = self._post_data('message', {
            'name': message_name,
            'payload': payload
        }).json()
        
        self.response_callbacks[response['message_id']] = get_blocking_callback(response["message_id"])
        self.outstanding_responses[response["message_id"]] = 1
        
        block_start_time = time.time()
        block_current_time = block_start_time
        
        while not self.blocking_store[response["message_id"]]:
            time.sleep(self.poll_wait/1000)
                
            block_current_time = time.time()
            if block_current_time - block_start_time > self.block_timeout_time:
                return None

            responses = self._poll_responses()
            
            if not self._dispatch_responses(responses):
                self.stop()
                break;
                
            
        rv = self.blocking_store[response["message_id"]]
        del self.blocking_store[response["message_id"]]
        return rv

    def start(self):
        """
        Starts the tutor in event-driven mode.
        """
        self.run_loop = True;
        self.connect()
        
        try:
            while self.run_loop:
                if not self.callback():
                    break;

                time.sleep(self.poll_wait/1000)
                
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
