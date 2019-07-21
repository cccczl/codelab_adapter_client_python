"""Top-level package for codelab_adapter_client."""

__author__ = """Wenjie Wu"""
__email__ = 'wuwenjie718@gmail.com'
__version__ = '0.3.0'

import zmq
import time
import json
import logging
import sys
import threading
import msgpack
import queue
import psutil
from abc import ABCMeta, abstractmethod
from pathlib import Path
import importlib
import functools

ADAPTER_TOPIC = "from_adapter/extensions"
SCRATCH_TOPIC = "from_scratch/extensions"
NOTIFICATION_TOPIC = "notification"
EXTENSIONS_OPERATE_TOPIC = "adapter_core/extensions/operate"
logger = logging.getLogger(__name__)


def threaded(function):
    """
    https://github.com/malwaredllc/byob/blob/master/byob/core/util.py#L514

    Decorator for making a function threaded
    `Required`
    :param function:    function/method to run in a thread
    """

    @functools.wraps(function)
    def _threaded(*args, **kwargs):
        t = threading.Thread(
            target=function, args=args, kwargs=kwargs, name=time.time())
        t.daemon = True  # exit with the parent thread
        t.start()
        return t

    return _threaded


class MessageNode(metaclass=ABCMeta):
    def __init__(
            self,
            name='',
            logger=logger,
            codelab_adapter_ip_address=None,
            subscriber_port='16103',
            publisher_port='16130',
            subscriber_list=None,
            loop_time=0.1,
            connect_time=0.3,
            external_message_processor=None,
            receive_loop_idle_addition=None,
    ):
        '''
        :param codelab_adapter_ip_address: Adapter IP Address -
                                      default: 127.0.0.1
        :param subscriber_port: codelab_adapter subscriber port.
        :param publisher_port: codelab_adapter publisher port.
        :param loop_time: Receive loop sleep time.
        :param connect_time: Allow the node to connect to adapter
        '''
        self._running = True  # use it to receive_loop
        self.logger = logger
        self._running = True  # use it to control Python thread, work with self.terminate()
        if name:
            self.name = name
        else:
            self.name = type(self).__name__
        self.subscriber_list = subscriber_list
        self.receive_loop_idle_addition = receive_loop_idle_addition
        self.external_message_processor = external_message_processor
        self.connect_time = connect_time

        if codelab_adapter_ip_address:
            self.codelab_adapter_ip_address = codelab_adapter_ip_address
        else:
            # check for a running CodeLab Adapter
            # self.check_adapter_is_running()
            # determine this computer's IP address
            self.codelab_adapter_ip_address = '127.0.0.1'

        self.subscriber_port = subscriber_port
        self.publisher_port = publisher_port
        self.loop_time = loop_time

        self.logger.info(
            '\n************************************************************')
        self.logger.info('CodeLab Adapter IP address: ' +
                         self.codelab_adapter_ip_address)
        self.logger.info('Subscriber Port = ' + self.subscriber_port)
        self.logger.info('Publisher  Port = ' + self.publisher_port)
        self.logger.info('Loop Time = ' + str(loop_time) + ' seconds')
        self.logger.info(
            '************************************************************')

        # establish the zeromq sub and pub sockets and connect to the adapter
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        connect_string = "tcp://" + self.codelab_adapter_ip_address + ':' + self.subscriber_port
        self.subscriber.connect(connect_string)

        self.publisher = self.context.socket(zmq.PUB)
        connect_string = "tcp://" + self.codelab_adapter_ip_address + ':' + self.publisher_port
        self.publisher.connect(connect_string)

        # Allow enough time for the TCP connection to the adapter complete.
        time.sleep(self.connect_time)
        if self.subscriber_list:
            for topic in self.subscriber_list:
                self.set_subscriber_topic(topic)

    def __str__(self):
        return self.name

    def is_running(self):
        return self._running

    '''
    def check_adapter_is_running(self):
        adapter_exists = False
        for pid in psutil.pids():
            p = psutil.Process(pid)
            try:
                p_command = p.cmdline()
            except psutil.AccessDenied:
                # occurs in Windows - ignore
                continue
            try:
                if any('codelab' in s.lower() for s in p_command):
                    adapter_exists = True
                else:
                    continue
            except UnicodeDecodeError:
                continue

        if not adapter_exists:
            raise RuntimeError(
                'CodeLab Adapter is not running - please start it.')
    '''

    def set_subscriber_topic(self, topic):
        if not type(topic) is str:
            raise TypeError('Subscriber topic must be string')

        self.subscriber.setsockopt(zmq.SUBSCRIBE, topic.encode())

    def publish_payload(self, payload, topic=''):
        if not type(topic) is str:
            raise TypeError('Publish topic must be string', 'topic')

        # create message pack payload
        message = msgpack.packb(payload, use_bin_type=True)

        pub_envelope = topic.encode()
        self.publisher.send_multipart([pub_envelope, message])


    def receive_loop(self):
        """
        This is the receive loop for receiving sub messages.
        """
        while self._running:
            try:
                data = self.subscriber.recv_multipart(zmq.NOBLOCK)  # NOBLOCK
                topic = data[0].decode()
                payload = msgpack.unpackb(data[1], raw=False)
                self.message_handle(topic, payload)
            # if no messages are available, zmq throws this exception
            except zmq.error.Again:
                try:
                    if self.receive_loop_idle_addition:
                        self.receive_loop_idle_addition()
                    time.sleep(self.loop_time)
                except KeyboardInterrupt:
                    self.clean_up()
                    raise KeyboardInterrupt
            '''
            except msgpack.exceptions.ExtraData as e:
                self.logger.error(str(e))
            '''

    def receive_loop_as_thread(self):
        threaded(self.receive_loop)()

    def message_handle(self, topic, payload):
        """
        Override this method with a custom adapter message processor for subscribed messages.
        """
        print(
            'message_handle method should provide implementation in subclass.')

    def clean_up(self):
        """
        Clean up before exiting.
        """
        self._running = False
        time.sleep(0.1)
        self.publisher.close()
        self.subscriber.close()
        self.context.term()


class AdapterNode(MessageNode):
    '''
    CodeLab Adapter Node
    
    todo: Extension.
    '''
    message_types = [
        "notification", "from_scratch", "from_adapter", "current_extension"
    ]

    def __init__(
            self,
            name='',
            logger=logger,
            codelab_adapter_ip_address=None,
            subscriber_port='16103',
            publisher_port='16130',
            subscriber_list=[SCRATCH_TOPIC, EXTENSIONS_OPERATE_TOPIC],
            loop_time=0.1,
            connect_time=0.3,
            external_message_processor=None,
            receive_loop_idle_addition=None,
    ):
        '''
        :param codelab_adapter_ip_address: Adapter IP Address -
                                      default: 127.0.0.1
        :param subscriber_port: codelab_adapter subscriber port.
        :param publisher_port: codelab_adapter publisher port.
        :param loop_time: Receive loop sleep time.
        :param connect_time: Allow the node to connect to adapter
        '''
        super().__init__(name, logger, codelab_adapter_ip_address,
                         subscriber_port, publisher_port, subscriber_list,
                         loop_time, connect_time, external_message_processor,
                         receive_loop_idle_addition)

        self.ADAPTER_TOPIC = ADAPTER_TOPIC  # message topic: the message from adapter
        self.SCRATCH_TOPIC = SCRATCH_TOPIC  # message topic: the message from scratch
        self.EXTENSION_ID = "eim"
        # todo  handler: https://github.com/offu/WeRoBot/blob/master/werobot/robot.py#L590
        self._handlers = {k: [] for k in self.message_types}
        self._handlers['all'] = []

    def __str__(self):
        return self.name

    def add_handler(self, func, type='all'):
        """
        add message handler to Extension instance。
        :param func:  handler method
        :param type: handler type

        :return: None
        """
        if not callable(func):
            raise ValueError("{} is not callable".format(func))

        self._handlers[type].append(func)

    def get_handlers(self, type):
        return self._handlers.get(type, []) + self._handlers['all']

    def handler(self, f):
        """
        add handler to every message.
        """
        self.add_handler(f, type='all')
        return f

    # def extension_message_handle(self, f):
    def extension_message_handle(self, topic, payload):
        """
        the decorator for adding current_extension handler
        
        self.add_handler(f, type='current_extension')
        return f
        """
        self.logger.info("please set the  method to your handle method")

    def exit_message_handle(self, topic, payload):
        self.logger.info("please set the  method to your handle method")

    def publish(self, message):
        assert isinstance(message, dict)
        topic = message.get('topic')
        payload = message.get("payload")
        if not topic:
            topic = self.ADAPTER_TOPIC
        if not payload.get("extension_id"):
            payload["extension_id"] = self.get_extension_id()
        self.logger.debug(
            f"{self.name} publish: topic: {topic} payload:{payload}")

        self.publish_payload(payload, topic)

    def get_extension_id(self):
        return self.EXTENSION_ID

    def pub_notification(self, content, topic=NOTIFICATION_TOPIC, type="INFO"):
        '''
        type
            ERROR
            INFO
        {
            topic: "from_adapter/extensions/notification"
            payload: {

                content:
            }
        }
        '''
        extension_id = self.get_extension_id()
        payload = {"type": type, "extension_id": extension_id}
        payload["content"] = content
        self.publish_payload(payload, topic)

    def pub_status(self, statu):
        topic = ADAPTER_TOPIC + "/status"
        extension_id = self.get_extension_id()
        payload = {"extension_id": extension_id}
        payload["content"] = statu
        self.publish_payload(payload, topic)


    def receive_loop_as_thread(self):
        threaded(self.receive_loop)()

    def message_handle(self, topic, payload):
        """
        Override this method with a custom adapter message processor for subscribed messages.
        :param topic: Message Topic string.
        :param payload: Message Data.

        all the sub message
        process handler
        """
        if topic == SCRATCH_TOPIC:
            if payload.get("extension_id") == self.get_extension_id():
                self.extension_message_handle(topic, payload)
                '''
                handlers = self.get_handlers(type="current_extension")
                for handler in handlers:
                    handler(topic, payload)
                '''
        if topic == EXTENSIONS_OPERATE_TOPIC:
            if payload.get("extension_id") == self.get_extension_id():
                self.exit_message_handle(topic, payload)
        # adapter_core/extensions/operate {'content': 'stop', 'extension_id': 'extension_eim_monitor'}
        if self.external_message_processor:
            self.external_message_processor(topic, payload)

    def terminate(self):
        '''
        stop thread
        '''
        self.clean_up()
        self.logger.info(f"{self} terminate!")