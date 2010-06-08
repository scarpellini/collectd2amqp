# -*- coding: utf8 -*-
#
# Eduardo S. Scarpellini, <scarpellini@gmail.com>
#
#   Licensed to the Apache Software Foundation (ASF) under one
#   or more contributor license agreements.  See the NOTICE file
#   distributed with this work for additional information
#   regarding copyright ownership.  The ASF licenses this file
#   to you under the Apache License, Version 2.0 (the
#   "License"); you may not use this file except in compliance
#   with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing,
#   software distributed under the License is distributed on an
#   "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#   KIND, either express or implied.  See the License for the
#   specific language governing permissions and limitations
#   under the License.
import collectd
import Queue
from threading import Thread
import simplejson
from amqplib import client_0_8 as amqplib


class ThreadManager(object):
	"""Manage the internal ThreadPool (workers which send the messages to the AMQP server)
	"""

	def __init__(self, config={}):
		self.config = config
		self.thramount = self.config["threads"]
		self.thrpool = []
		self.job_queue = Queue.Queue(maxsize=20000)

	def start(self):
		"""Start the threads (workers)
		"""

		collectd.info("2AMQP: Starting threads...")

		for i in xrange(0, self.thramount):
			thr = AMQPWorker(queue=self.job_queue, 
				amqp_server=self.config["amqp_server"],
				amqp_port=self.config["amqp_port"],
       		         	amqp_vhost=self.config["amqp_vhost"],
				amqp_user=self.config["amqp_user"],
				amqp_passwd=self.config["amqp_passwd"],
				amqp_exchange=self.config["amqp_exchange"],
				amqp_routekey=self.config["amqp_routekey"],
				amqp_delivery_mode=self.config["amqp_delivery_mode"])
			thr.start()
			self.thrpool.append(thr)

	def stop(self):
		"""Stop the threads (workers) via messaging (safe)
		"""

		collectd.info("2AMQP: Stopping threads...")

		for i in self.thrpool:
			self.job_queue.put((1, None))

	def add_job(self, vl):
		"""Add a 'job' to job queue
		"""

		self.job_queue.put((0, vl))


class AMQPWorker(Thread):
	"""Worker for communication with the AMQP server
	"""

	def __init__(self, queue, amqp_server, amqp_port, amqp_vhost, amqp_user,
		amqp_passwd, amqp_exchange, amqp_routekey, amqp_delivery_mode, *args, **kwargs):

		self.job_queue = queue
		self.amqp_server = amqp_server
		self.amqp_port = amqp_port
		self.amqp_vhost = amqp_vhost
		self.amqp_user = amqp_user
		self.amqp_passwd = amqp_passwd
		self.amqp_exchange = amqp_exchange
		self.amqp_routekey = amqp_routekey
		self.amqp_connection = None
		self.amqp_channel = None
		self.amqp_delivery_mode = amqp_delivery_mode

		Thread.__init__(self, *args, **kwargs)

	def run(self):
		"""Read the internal queue and send the msg to the AMQP client (self.__amqp_send)
		"""

		collectd.info("2AMQP: Starting %s..." % self.getName())

		self.__amqp_connect()

		while True:
			msg = self.job_queue.get()

			# stop worker (ThreadManager.stop())
			if msg[0] == 1:
				collectd.info("2AMQP: %s - Stopping..." % self.getName())

				self.__amqp_disconnect()
				break

			self.__amqp_send(msg={
				"host": msg[1].host,
				"interval": msg[1].interval,
				"plugin": msg[1].plugin,
				"plugin_instance": msg[1].plugin_instance,
				"time": msg[1].time,
				"type":	msg[1].type,
				"type_instance": msg[1].type_instance,
				"values": msg[1].values }
			)

	def __amqp_connect(self):
		"""Connect to the AMQP server
		"""

		collectd.info("2AMQP: %s - Connecting to the AMQP server..." % self.getName())

		try:
			self.amqp_connection = amqplib.Connection(
				host="%s:%s" % (self.amqp_server, str(self.amqp_port)),
				userid=self.amqp_user,
				password=self.amqp_passwd,
				virtual_host=self.amqp_vhost,
				insist=False)

			self.amqp_channel = self.amqp_connection.channel()

		except Exception, e:
			collectd.error("2AMQP: %s - Error in establishing AMQP connection %s" % (self.getName(), e))

	def __amqp_disconnect(self):
		"""Close the AMQP connection
		"""

		self.amqp_channel.close()
		self.amqp_connection.close()

	def __amqp_send(self, msg={}):
		"""Send the message to the AMQP server
		"""

		jmsg = simplejson.dumps(msg)
		amsg = amqplib.Message("%s" % msg)

		amsg.properties["delivery_mode"] = self.amqp_delivery_mode

		self.amqp_channel.basic_publish(amsg, exchange=self.amqp_exchange, routing_key=self.amqp_routekey)


class Collectd2AMQP(object):
	"""Dispatch the messages to the ThreadPool
	"""

	def __init__(self, config={}):
		self.thrman = None
		self.config = config
		self._start_workers()

	def _start_workers(self):
		"""Start the ThreadManager
		"""
		self.thrman = ThreadManager(config=self.config)
		self.thrman.start()

	def write(self, vl):
		"""Write the messages to the internal queue
		"""

		self.thrman.add_job(vl)

	def shutdown(self):
		"""Shutdown the workers
		"""

		self.thrman.stop()



def config(vl, data={}):
	collectd.info("2AMQP: Configuring...")

	data["config"] = dict( [(x.key, x.values[0]) for x in vl.children] )

	data["config"]["amqp_delivery_mode"] = int(data["config"]["amqp_delivery_mode"])

	data["config"]["threads"] = int(data["config"]["threads"])
	if data["config"]["threads"] < 1:
		data["config"]["threads"] = 1

def init(data={}):
	collectd.info("2AMQP: Initializing...")

	data["2amqp"] = Collectd2AMQP(config=data["config"])

def write(vl, data={}):
	data["2amqp"].write(vl)

def shutdown(data={}):
	collectd.info("2AMQP: Shutting down...")

	data["2amqp"].shutdown()



data = {}

collectd.info("2AMQP: Starting plugin...")

collectd.register_config(callback=config, data=data)
collectd.register_init(callback=init, data=data)
collectd.register_write(callback=write, data=data)
collectd.register_shutdown(callback=shutdown, data=data)
