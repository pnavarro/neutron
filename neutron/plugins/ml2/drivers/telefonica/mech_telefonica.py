# Copyright 2013 OpenStack Foundation
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
ML2 Mechanism Driver for Floodlight when using direct type ports (SRIOV)
"""

import yaml
import openflow_fl as of

from oslo.config import cfg

from neutron.common import constants
from neutron.extensions import portbindings
from neutron.openstack.common import log
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers.telefonica import db as tef_db
from neutron.openstack.common import jsonutils

LOG = log.getLogger(__name__)

telefonica_opts = [
    cfg.StrOpt('server', default='localhost',
                help=_("The Big Switch/Floodlight server host")),
    cfg.IntOpt('port', default=8800,
                help=_("The Big Switch/Floodlight server port"
                       "number.")),
    cfg.StrOpt('switch_connections_file_path',
                default='/etc/neutron/plugins/ml2/ml2_tef_switch_connections.yaml',
                help=_("The YAML data path file with switch connections "
                       "information.")),
]

cfg.CONF.register_opts(telefonica_opts, "ml2_telefonica")


class TelefonicaMechanismDriver(api.MechanismDriver):

    """Telefonica ML2 Mechanism Driver."""

    def initialize(self,
                 agent_type=constants.AGENT_TYPE_NIC_SWITCH,
                 vif_type=portbindings.VIF_TYPE_HW_VEB,
                 vif_details={portbindings.CAP_PORT_FILTER: False},
                 supported_vnic_types=[portbindings.VNIC_DIRECT,
                                       portbindings.VNIC_MACVTAP],
                 supported_pci_vendor_info=None):
        # Create ML2 device dictionary from ml2_conf.ini entries.
        self.supported_vnic_types = supported_vnic_types
        # register plugin config opts
        self.server = cfg.CONF.ml2_telefonica.server
        self.port = cfg.CONF.ml2_telefonica.port
        self.switch_connections_file_path = cfg.CONF.ml2_telefonica.switch_connections_file_path
        self.vif_details = vif_details
        self.switch_port_info = self.initialize_switch_port_info()
        self._db = tef_db.TelefonicaDbMixin()
        self.supported_vnic_types = supported_vnic_types
        self.vif_type = vif_type
        self.vif_details = vif_details

    def bind_port(self, context):
        """Marks ports as bound.

        Binds external ports and IVS ports.
        Fabric configuration will occur on the subsequent port update.
        Currently only vlan segments are supported.
        """
        LOG.debug("Attempting to bind port %(port)s on "
                  "network %(network)s",
                  {'port': context.current['id'],
                   'network': context.network.current['id']})
        vnic_type = context.current.get(portbindings.VNIC_TYPE,
                                        portbindings.VNIC_NORMAL)
        if vnic_type not in self.supported_vnic_types:
            LOG.debug("Refusing to bind due to unsupported vnic_type: %s",
                      vnic_type)
            return

        # This is the port list of already configured ports
        port_list = []

        # Bind the host
        self.try_to_bind(context)
        # Get current port
        this_port = self._get_current_port(context)
        network_id = context.network.current['id']
        sriov_connection_ports = self._get_net_ports(network_id, this_port['id'])

        port_list.extend(sriov_connection_ports)
        port_list.append(this_port)

        port_byswitch_list = self._get_switch_connections(self.switch_port_info, port_list)

        self._connect(self.server, self.port, port_byswitch_list, network_id)

    def try_to_bind(self, context, agent=None):
        for segment in context.network.network_segments:
            if self.check_segment(segment, agent):
                context.set_binding(segment[api.ID],
                                    self.vif_type,
                                    self.get_vif_details(context, segment),
                                    constants.PORT_STATUS_ACTIVE)
                LOG.debug("Bound using segment: %s", segment)
                return True
        return False

    def check_segment(self, segment, agent=None):
        """Check if segment can be bound.

        :param segment: segment dictionary describing segment to bind
        :param agent: agents_db entry describing agent to bind or None
        :returns: True if segment can be bound for agent
        """
        network_type = segment[api.NETWORK_TYPE]
        if network_type == p_const.TYPE_VLAN:
            if agent:
                mappings = agent['configurations'].get('device_mappings', {})
                LOG.debug("Checking segment: %(segment)s "
                          "for mappings: %(mappings)s ",
                          {'segment': segment, 'mappings': mappings})
                return segment[api.PHYSICAL_NETWORK] in mappings
            return True
        return False

    def get_vif_details(self, context, segment):
        if segment[api.NETWORK_TYPE] == p_const.TYPE_VLAN:
            vlan_id = str(segment[api.SEGMENTATION_ID])
            self.vif_details[portbindings.VIF_DETAILS_VLAN] = vlan_id
        return self.vif_details

    def delete_port_postcommit(self, context):
        # delete port on the network controller
        # TODO Add the functions to call to the StaticFlow API to remove the flows
        port = context.current
        network_id = context.network.current['id']
        switch_dpid = self.switch_port_info["switches"][0]['switch_dpid']
        list_flows_to_remove = self._get_list_of_flows_to_remove(port, network_id)
        self._disconnect(self.server, self.port, list_flows_to_remove, switch_dpid)
        pass

    def _get_switch_connections(self, switch_port_info, port_list):
        #TODO: Ready only for one switch. This is why 0 is used when reading the list in switch_port_info["switches"]
        switch = switch_port_info["switches"][0]
        LOG.debug("This is the Switch info from the YAML: %s" % switch_port_info)
        LOG.debug("This is the present Switch info : %s" % switch)
        port_byswitch_list = {}
        for port in port_list:
            port_found = False
            switch_ports = switch["ports"]
            for switch_port in switch_ports:
                #if it is an external port just check 'alias'
                #if not 'host_id' in switch_port and not 'phys_function_address' in switch_port and not 'mac_address' in switch_port and  'switch_port' in switch_port and not 'host' in port:
                #    if port["alias"] == switch_port["alias"]:
                #        port["input_port"] = switch_port["switch_port"]
                #        if not port["dpid"] in port_byswitch_list:
                #            port_byswitch_list[ port["dpid"] ] = list()
                #        port_byswitch_list[ port["dpid"] ].append(port)
                #        port_found = True
                #        break
                #    else:
                #        continue
                #we only get in the else if the port is not an external port
                if 'host' in port and 'host_id' in switch_port:
                    if port["pci"] in switch_port["phys_function_address"] and port["host"] in switch_port["host_id"]:
                        port_found=True
                        port["input_port"] = switch_port["switch_port"]
                        if "mac_address" not in port and port["vlan"]==None and "mac_address" in switch_port:
                            port["mac_address"] = switch_port["mac_address"]
                        if switch_port_info["switches"][0]['switch_dpid'] not in port_byswitch_list:
                            port_byswitch_list[ switch_port_info["switches"][0]['switch_dpid'] ] = []
                        port_byswitch_list[ switch_port_info["switches"][0]['switch_dpid'] ].append(port)
                        break
        #if len(port_byswitch_list[ switch_port_info["switches"][0]['switch_dpid'] ]) < 2:
        #    LOG.error("DataPlane_Net._get_switch_connections(): Less than 2 ports to connect for 'switch_id': "+
        #              switch_port_info["switches"][0]['switch_dpid'] + " skipping")

        LOG.debug("DataPlane_Net._get_switch_connections(): port_byswitch_list: " + str(port_byswitch_list) )
        return port_byswitch_list

    def _connect(self, of_ip, of_port, port_byswitch_list, net_name):
        openflow = of.OpenFlow_FL(of_ip, of_port)
        result,data,error_text = openflow.connect(port_byswitch_list, net_name)
        if result < 0:
            LOG.error("DataPlane_Net._connect(): " + error_text )
            raise ValueError(_(error_text ) )
        LOG.debug("DataPlane_Net._connect(): created %d rules, data %s " % (result, str(data) ) )
        return data

    def _disconnect(self, of_ip, of_port, list_of_flows_to_remove, switch_dpid):
        openflow = of.OpenFlow_FL(of_ip, of_port)
        result,data,error_text = openflow.disconnect(list_of_flows_to_remove, switch_dpid)
        if result<0:
            LOG.error("DataPlane_Net._disconnect(): " + error_text )
            raise ValueError(_(error_text ) )
        LOG.debug("DataPlane_Net._disconnect(): %d openflow rules deleted" % result)

    def initialize_switch_port_info(self):
        '''
        Validates switch_port_info properties
        '''
        try:
            stream = open(self.switch_connections_file_path, 'r')
            switch_port_info = yaml.load(stream)
            return switch_port_info
        except yaml.YAMLError, exc:
            error_pos = ""
            if hasattr(exc, 'problem_mark'):
              mark = exc.problem_mark
              error_pos = " at position: (%s:%s)" % (mark.line+1, mark.column+1)
            msg = _('Invalid format'+error_pos)
            raise  cfg.Error(_(message=msg))

    def _get_net_ports(self, network_id, current_port_id):
        sriov_connection_ports = []
        if not network_id:
            LOG.debug("DataPlane_Net._get_net_ports(): empty list of SRIOV ports")
            return []
        ports = self._db.get_network_ports(network_id)
        LOG.debug ("This is the current port_id:%s" % current_port_id)
        for port in ports:
            port_id = port['port_id']
            LOG.debug ("Getting the port: %s" % port_id)
            port_name = port.get('name')
            if current_port_id in port_id:
                continue
            if 'direct' not in port['vnic_type']:
                LOG.error("Port " +port_id+" "+port_name+" not of binding:vnic_type: 'direct' can not be connected to a data plane net!!!")
                continue
            if 'unbound' in port['vif_type']:
                continue
            vif_details_str = port['vif_details']
            vif_details = jsonutils.loads(vif_details_str)
            port_info = {"server_id": port.get("server_uuid"), "mac_address": port.get("mac_address"), "id":port_id,
                         "name":port_name, "vlan": vif_details['vlan'], "host": port.get("host")}

            #find information from the list of pci devices
            profile_str = port["profile"]
            profile = jsonutils.loads(profile_str)
            phys_function = self._get_phys_function_from_virtual_function(profile["pci_slot"])
            port_info["pci"] = phys_function
            # Not possible to easily get where the port is hosted port_info["host"]
            sriov_connection_ports.append(port_info)
        LOG.debug("DataPlane_Net._get_net_ports(): List of SRIOV ports: %s" % str(sriov_connection_ports))
        return sriov_connection_ports

    def _get_phys_function_from_virtual_function(self, virtual_function_address):
        pci_vf_splitted = virtual_function_address.split(':')
        last_segment = int(virtual_function_address[virtual_function_address.find('.')+1:])
        phys_function_address = "%s:%s:%s.%s" % (
                                        pci_vf_splitted[0],
                                        pci_vf_splitted[1],
                                        '00',
                                        str(last_segment % 2)
        )
        return phys_function_address

    def _get_current_port(self, context):
        port = context.current
        port_name = port.get('name')
        port_id = port['id']
        binding = context._binding
        vif_details_str = binding.vif_details
        vif_details = jsonutils.loads(vif_details_str)
        port_info = {"server_id": port.get("server_uuid"), "mac_address": port.get("mac_address"), "id":port_id, "name":port_name }
        port_info["vlan"] = vif_details['vlan']
        profile_str = binding.profile
        profile = jsonutils.loads(profile_str)
        LOG.debug ("My binding profile: %s" % str(profile_str))
        phys_function = self._get_phys_function_from_virtual_function(profile["pci_slot"])
        port_info["pci"] = phys_function
        port_info["host"] = binding.host
        return port_info

    def _get_list_of_flows_to_remove(self, current_port, network_id):
        ports = self._db.get_network_ports(network_id)
        flows_to_remove = []
        for port_2 in ports:
            if current_port['id'] == port_2['port_id']:
                continue
            flow_name = network_id+'-'+str(current_port['id'])
            flow_name += '-'+str(port_2['port_id'])
            flows_to_remove.append(flow_name)
            flow_inverse_name = network_id+'-'+str(port_2['port_id'])
            flow_inverse_name += '-'+str(current_port['id'])
            flows_to_remove.append(flow_inverse_name)
        #Tries to remove the Broadcast too
        flow_name = network_id+'-'+str(current_port['id'])
        flow_name += '-'+'Broadcast'
        flows_to_remove.append(flow_name)
        return flows_to_remove