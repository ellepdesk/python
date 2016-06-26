import logging
from copy import copy

import tornado
from tornado.locks import Event

import pubnub as pn

from tornado.testing import AsyncTestCase
from pubnub.callbacks import SubscribeCallback
from pubnub.pubnub_tornado import PubNubTornado
from tests import helper
from tests.helper import pnconf
from tests.integrational.tornado.tornado_helper import ExtendedSubscribeCallback

pn.set_stream_logger('pubnub', logging.DEBUG)

ch1 = "ch1"
ch2 = "ch2"


class SubscriptionTest(object):
    def __init__(self):
        super(SubscriptionTest, self).__init__()
        self.pubnub = None


class TestMultipleChannelSubscriptions(AsyncTestCase, SubscriptionTest):
    def setUp(self):
        super(TestMultipleChannelSubscriptions, self).setUp()
        self.pubnub = PubNubTornado(pnconf, custom_ioloop=self.io_loop)

    def test_do(self):
        _test = self

        class MyCallback(SubscribeCallback):
            def __init__(self):
                self.subscribe = False
                self.unsubscribe = False

            def message(self, pubnub, result):
                _test.io_loop.add_callback(_test._unsubscribe)

            def status(self, pubnub, status):
                # connect event triggers only once, but probably should be triggered once for each channel
                # TODO collect 3 subscribe
                # TODO collect 3 unsubscribe
                if helper.is_subscribed_event(status):
                    self.subscribe = True
                    _test.io_loop.add_callback(_test._publish)
                elif helper.is_unsubscribed_event(status):
                    self.unsubscribe = True
                    pubnub.stop()
                    _test.stop()

            def presence(self, pubnub, presence):
                pass

        callback = MyCallback()
        self.pubnub.add_listener(callback)
        self.pubnub.subscribe().channels("ch1").execute()
        self.pubnub.subscribe().channels("ch2").execute()
        self.pubnub.subscribe().channels("ch3").execute()

        self.wait()

    def _publish(self):
        self.pubnub.publish().channel("ch2").message("hey").future()

    def _unsubscribe(self):
        self.pubnub.unsubscribe().channels(["ch1", "ch2"]).execute()
        self.io_loop.add_callback(self._unsubscribe2)

    def _unsubscribe2(self):
        self.pubnub.unsubscribe().channels(["ch3"]).execute()


class TestSubscribeUnsubscribe(AsyncTestCase, SubscriptionTest):
    def setUp(self):
        super(TestSubscribeUnsubscribe, self).setUp()
        self.pubnub = PubNubTornado(pnconf, custom_ioloop=self.io_loop)

    def test_do(self):
        _test = self

        class MyCallback(SubscribeCallback):
            def message(self, pubnub, result):
                pass

            def status(self, pubnub, status):
                if helper.is_subscribed_event(status):
                    _test.io_loop.add_callback(_test.unsubscribe)
                elif helper.is_unsubscribed_event(status):
                    pubnub.stop()
                    _test.stop()

            def presence(self, pubnub, presence):
                pass

        callback = MyCallback()
        self.pubnub.add_listener(callback)
        self.pubnub.subscribe().channels("ch1").execute()
        self.pubnub.start()
        self.wait()

    def unsubscribe(self):
        self.pubnub.unsubscribe().channels(["ch1", "ch2"]).execute()


class TestPresenceJoinLeave(AsyncTestCase, SubscriptionTest):
    @tornado.testing.gen_test(timeout=15)
    def test_do(self):
        self.pubnub = PubNubTornado(copy(pnconf), custom_ioloop=self.io_loop)
        self.pubnub_listener = PubNubTornado(copy(pnconf), custom_ioloop=self.io_loop)
        self.pubnub.config.uuid = helper.gen_channel("messenger")
        self.pubnub_listener.config.uuid = helper.gen_channel("listener")
        callback_presence = ExtendedSubscribeCallback()
        self.pubnub_listener.add_listener(callback_presence)
        self.pubnub_listener.subscribe().channels("ch1").with_presence().execute()
        yield callback_presence.wait_for_connect()

        envelope = yield callback_presence.wait_for_presence_on("ch1")
        assert envelope.actual_channel == "ch1-pnpres"
        assert envelope.event == 'join'
        assert envelope.uuid == self.pubnub_listener.uuid

        callback_messages = ExtendedSubscribeCallback()
        self.pubnub.add_listener(callback_messages)
        self.pubnub.subscribe().channels("ch1").execute()
        yield callback_messages.wait_for_connect()

        envelope = yield callback_presence.wait_for_presence_on("ch1")
        assert envelope.actual_channel == "ch1-pnpres"
        assert envelope.event == 'join'
        assert envelope.uuid == self.pubnub.uuid

        self.pubnub.unsubscribe().channels("ch1").execute()
        yield callback_messages.wait_for_disconnect()

        envelope = yield callback_presence.wait_for_presence_on("ch1")
        assert envelope.actual_channel == "ch1-pnpres"
        assert envelope.event == 'leave'
        assert envelope.uuid == self.pubnub.uuid

        self.pubnub_listener.unsubscribe().channels("ch1").execute()
        yield callback_presence.wait_for_disconnect()
        self.pubnub.stop()
        self.stop()