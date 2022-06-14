# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, Chongqing, China.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, Intf, TCLink
from mininet.topo import Topo
from mininet.util import dumpNodeConnections
from time import sleep
import re

import logging
import os

K = 4
CONTROLLER_IP ='192.168.56.104'
CONTROLLER_PORT = 6653
HOSTS = K**3/4

class Fattree(Topo):
	"""
		Class of Fattree Topology.
	"""
	CoreSwitchList = []
	AggSwitchList = []
	EdgeSwitchList = []
	HostList = []

	def __init__(self, k, density):
		self.pod = k
		self.density = int(density)
		self.iCoreLayerSwitch = int((k/2)**2)
		self.iAggLayerSwitch = int(k*k/2)
		self.iEdgeLayerSwitch = int(k*k/2)
		self.iHost = int(self.iEdgeLayerSwitch * density)

		# Init Topo
		Topo.__init__(self)

	def createNodes(self):
		self.createCoreLayerSwitch(self.iCoreLayerSwitch)
		self.createAggLayerSwitch(self.iAggLayerSwitch)
		self.createEdgeLayerSwitch(self.iEdgeLayerSwitch)
		self.createHost(self.iHost)

	# Create Switch and Host
	def _addSwitch(self, number, level, switch_list):
		"""
			Create switches.
		"""
		for i in range(1, int(number+1)):
			PREFIX = str(level) + "00"
			if i >= 10:
				PREFIX = str(level) + "0"
			switch_list.append(self.addSwitch(PREFIX + str(i)))

	def createCoreLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 1, self.CoreSwitchList)

	def createAggLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 2, self.AggSwitchList)

	def createEdgeLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 3, self.EdgeSwitchList)

	def createHost(self, NUMBER):
		"""
			Create hosts.
		"""
		for i in range(1, int(NUMBER+1)):
			if i >= 100:
				PREFIX = "h"
			elif i >= 10:
				PREFIX = "h0"
			else:
				PREFIX = "h00"
			self.HostList.append(self.addHost(PREFIX + str(i), cpu=1.0/NUMBER))

	def createLinks(self, bw_c2a=10, bw_a2e=10, bw_e2h=10):
		"""
			Add network links.
		"""
		# Core to Agg
		end = int(self.pod/2)
		for x in range(0, self.iAggLayerSwitch, end):
			for i in range(0, end):
				for j in range(0, end):
					self.addLink(
						self.CoreSwitchList[i*end+j],
						self.AggSwitchList[x+i],
						bw=bw_c2a, max_queue_size=1000)   # use_htb=False

		# Agg to Edge
		for x in range(0, self.iAggLayerSwitch, end):
			for i in range(0, end):
				for j in range(0, end):
					self.addLink(
						self.AggSwitchList[x+i], self.EdgeSwitchList[x+j],
						bw=bw_a2e, max_queue_size=1000)   # use_htb=False

		# Edge to Host
		for x in range(0, self.iEdgeLayerSwitch):
			for i in range(0, self.density):
				self.addLink(
					self.EdgeSwitchList[x],
					self.HostList[self.density * x + i],
					bw=bw_e2h, max_queue_size=1000)   # use_htb=False

	def set_ovs_protocol_13(self,):
		"""
			Set the OpenFlow version for switches.
		"""
		self._set_ovs_protocol_13(self.CoreSwitchList)
		self._set_ovs_protocol_13(self.AggSwitchList)
		self._set_ovs_protocol_13(self.EdgeSwitchList)

	def _set_ovs_protocol_13(self, sw_list):
		for sw in sw_list:
			cmd = "sudo ovs-vsctl set bridge %s protocols=OpenFlow13" % sw
			os.system(cmd)


def set_host_ip(net, topo):
	hostlist = []
	for k in range(len(topo.HostList)):
		hostlist.append(net.get(topo.HostList[k]))
	i = 1
	j = 1
	for host in hostlist:
		host.setIP("10.%d.0.%d" % (i, j))
		j += 1
		if j == topo.density+1:
			j = 1
			i += 1

def create_subnetList(topo, num):
	"""
		Create the subnet list of the certain Pod.
	"""
	subnetList = []
	remainder = num % (topo.pod/2)
	if topo.pod == 4:
		if remainder == 0:
			subnetList = [num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1]
		else:
			pass
	elif topo.pod == 8:
		if remainder == 0:
			subnetList = [num-3, num-2, num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1, num+2, num+3]
		elif remainder == 2:
			subnetList = [num-1, num, num+1, num+2]
		elif remainder == 3:
			subnetList = [num-2, num-1, num, num+1]
		else:
			pass
	else:
		pass
	return subnetList

def install_proactive(net, topo):
	"""
		Install direct flow entries for edge switches.
	"""
	# Edge Switch
	for sw in topo.EdgeSwitchList:
		num = int(sw[-2:])

		# Downstream.
		for i in range(1, topo.density+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)

	# Aggregate Switch
	# Downstream.
	for sw in topo.AggSwitchList:
		num = int(sw[-2:])
		subnetList = create_subnetList(topo, num)

		k = 1
		for i in subnetList:
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			k += 1

	# Core Switch
	for sw in topo.CoreSwitchList:
		j = 1
		k = 1
		for i in range(1, len(topo.EdgeSwitchList)+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			k += 1
			if k == topo.pod/2 + 1:
				j += 1
				k = 1

def iperfTest(net, topo):
	"""
		Start iperf test.
	"""
	h001, h015, h016 = net.get(
		topo.HostList[0], topo.HostList[14], topo.HostList[15])
	# iperf Server
	h001.popen('iperf -s -u -i 1 > iperf_server_differentPod_result', shell=True)
	# iperf Server
	h015.popen('iperf -s -u -i 1 > iperf_server_samePod_result', shell=True)
	# iperf Client
	h016.cmdPrint('iperf -c ' + h001.IP() + ' -u -t 10 -i 1 -b 10m')
	h016.cmdPrint('iperf -c ' + h015.IP() + ' -u -t 10 -i 1 -b 10m')

def pingAllTest(net):
	output = net.pingAll()
	r = r'Results: (\d+)'
	m = re.search(r, output)
	if m is None:
		print("Error: could not parse ping output: %s\n")
		return -1
	dropped = float(m.group(1))
	return dropped

def run_bootstrap(net):
	print("Running bootstrap...")	
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK BOOTSTRAP")
	else:
		print("NOT FULL CONNECTIVITY AT BOOTSTRAP")

def run_node_failure(net):
	print(f"Running Node Failure test...")
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('h001'), allLinks = True)
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('h002'), allLinks = True)
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('2001'), allLinks = True)
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('2002'), allLinks = True)
	print(f"deleted node 3001, waiting {K}s to reconverge")
	sleep(K)
	dropped_p = net.pingAll()
	total = HOSTS*(HOSTS-1)
	expected_d = total - 4*(HOSTS-1) #two hosts unreachable 
	expected_p = expected_d/total
	if (dropped_p == expected_p):
		print("OK Node Failure")
	else:
		print(f"Node Failure: fails, {dropped_p} dropped vs {expected_p} expected")

def run_node_recovery(net):
	print(f"Running Node Recovery test...")
	net.addLink (net.getNodeByName('3001'), net.getNodeByName('h001'))
	net.addLink (net.getNodeByName('3001'), net.getNodeByName('h002'))
	net.addLink (net.getNodeByName('3001'), net.getNodeByName('2001'))
	net.addLink (net.getNodeByName('3001'), net.getNodeByName('2002'))
	print("node 3001 up")
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK Node Recovery")
	else:
		print("Node Recovery: fails")

def run_link_failure(net):
	print(f"Running Link Failure test...")	
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('2001'), allLinks = True)
	print("link 3001 <-> 2001 down")
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK Link Failure")
	else:
		print("Link Failure: fails")

def run_link_recovery(net):	
	print(f"Running Link Recovery")	
	net.delLinkBetween (net.getNodeByName('3001'), net.getNodeByName('2001'), allLinks = True)
	print("link 3001 <-> 2001 down")
	sleep(3)
	net.addLink (net.getNodeByName('3001'), net.getNodeByName('2001'))
	print("link 3001 <-> 2001 up")
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK Link Recovery")
	else:
		print("Link Recovery: fails")

def run_partitioned_fabric(net):
	print(f"Running Partitioned Fabric")	
	net.delLinkBetween (net.getNodeByName('1001'), net.getNodeByName('2001'), allLinks = True)
	print("link 1001 <-> 2001 down")
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK Partitioned Fabric")
	else:
		print("Partitioned Fabric: fails")

def run_partitioned_fabric_plane(net):	
	print(f"Running Partitioned Fabric Plane")	
	net.delLinkBetween (net.getNodeByName('1001'), net.getNodeByName('2001'), allLinks = True)
	print("link 1001 <-> 2001 down")
	net.delLinkBetween (net.getNodeByName('1002'), net.getNodeByName('2001'), allLinks = True)
	print("link 1002 <-> 2001 down")
	dropped = net.pingAll()
	if (dropped == 0):
		print("OK Partitioned Fabric Plane")
	else:
		print("Partitioned Fabric Plane: fails")

def createTopo(pod, density, ip=CONTROLLER_IP, port=CONTROLLER_PORT, bw_c2a=10, bw_a2e=10, bw_e2h=10):
	"""
		Create network topology and run the Mininet.
	"""
	# Create Topo.
	topo = Fattree(pod, density)
	topo.createNodes()
	topo.createLinks(bw_c2a=bw_c2a, bw_a2e=bw_a2e, bw_e2h=bw_e2h)

	# Start Mininet.
	CONTROLLER_IP = ip
	CONTROLLER_PORT = port
	net = Mininet(topo=topo, link=TCLink, controller=None, autoSetMacs=True)
	net.addController(
		'controller', controller=RemoteController,
		ip=CONTROLLER_IP, port=CONTROLLER_PORT)
	net.start()

	# Set OVS's protocol as OF13.
	topo.set_ovs_protocol_13()
	# Set hosts IP addresses.
	set_host_ip(net, topo)
	# Install proactive flow entries
	install_proactive(net, topo)
	# dumpNodeConnections(net.hosts)
	# pingTest(net)
	# iperfTest(net, topo)
	sleep(30)
	#run_bootstrap(net)
	#uncomments the tests you wanna run
	run_node_failure(net)
	#run_node_recovery(net)
	#run_link_failure(net)
	#run_link_recovery(net)
	#run_partitioned_fabric(net)
	#run_partitioned_fabric_plane
	

	CLI(net)
	net.stop()

if __name__ == '__main__':
	setLogLevel('info')
	if os.getuid() != 0:
		logging.debug("You are NOT root")
	elif os.getuid() == 0:
		createTopo(4, 2)
		# createTopo(8, 4)
