import httplib
import json
from neutron.openstack.common import log


LOG = log.getLogger(__name__)


class OpenFlow_FL(object):

    def __init__(self, server, port):
        self.server = server
        self.port = port

    def get(self, data):
        ret = self.rest_call({}, 'GET')
        return json.loads(ret[2])

    def set(self, data):
        ret = self.rest_call(data, 'POST')
        return ret[0] == 200

    def remove(self, data):
        ret = self.rest_call(data, 'DELETE')
        return ret[0] == 200

    def rest_call(self, data, action):
        path = '/wm/staticflowentrypusher/json'
        headers = {
            'Content-type': 'application/json',
            'Accept': 'application/json',
            }
        body = json.dumps(data)
        conn = httplib.HTTPConnection(self.server, self.port)
        conn.request(action, path, body, headers)
        response = conn.getresponse()
        ret = (response.status, response.reason, response.read())
        conn.close()
        return ret
    
    def connect(self, connection_dict, net_name):
        '''Connect things
           connection_dict: Dictionary {dpid: [ connection1, connection2, ...    ]    } , 
           connection1: {mac_address:"", vlan: null, input_port: "switch_port"}
        '''
        created_connections={}
        if len(connection_dict) > 1: 
            return -2, {}, "This version does not allow the interconnection with more than one switch"
        index=0
        for dpid, connections in connection_dict.iteritems():
            nb_rules = len(connections)
            created_connections[dpid]={"start":index, "end":index}
            for con1 in connections:
                for con2 in connections:
                    if con1 == con2:
                        continue # avoid interconnection with itself
                    flow_name = net_name+'-'+str(con1['id'])
                    flow_name += '-'+str(con2['id'])
                    index += 1
                    flow = {
                        'switch': dpid,
                        "name": flow_name,
                        "priority":"1000",
                        "ingress-port": con1["input_port"],
                        "active":"true",
                        'actions':''
                    }
                    #allow that one port have no mac
                    if con2['mac_address'] is None or nb_rules==2: #point to point or nets with 2 elements
                        flow['priority'] = "990" #less priority
                    else:
                        flow['dst-mac'] = str(con2['mac_address'])
                    if con1['vlan'] != '0':
                        flow['vlan-id'] = str(con1['vlan'])
        
                    if con2['vlan'] == '0':
                        if con1['vlan'] != '0':
                            flow['actions'] = ''
                    else:
                        flow['actions'] = 'set-vlan-id='+str(con2['vlan'])+','
                    flow['actions'] += 'output='+  str(con2['input_port'])
        
            
                    result = self.rest_call(flow, "POST")
                    if result[0]!=200:
                        return -1, created_connections, "HTTP POST over '%s' return %d: %s" %(str(self.server)+":"+str(self.port), str(result[0]), str(result[1]) )
                    created_connections[dpid]["end"] = index
                    
            #BROADCAST:
            if nb_rules <= 2:
                return index, created_connections, None 
                #point to multipoint or nets with more than 2 elements
            for con1 in connections:
                flow = {
                        'switch': dpid,
                        "priority":"1000",
                        'dst-mac': 'ff:ff:ff:ff:ff:ff',
                        "active":"true",
                    }
                actions=''
                flow['ingress-port'] = str(con1['input_port'])
                flow_name = net_name+'-'+str(con1['id'])
                flow_name += '-'+'Broadcast'
                index += 1
                flow['name'] = flow_name
                if '0' not in con1['vlan']:
                    flow['vlan-id'] = str(con1['vlan'])
                    last_vlan=0 #indicates that a packet contains a vlan, and the vlan
                else:
                    last_vlan=None
                
                for con2 in connections:
                    if con1 == con2:
                        continue  # avoid interconnection with itshelf
                    if last_vlan != con2['vlan']:
                        if con2['vlan'] != '0':
                            actions += 'set-vlan-id='+str(con2['vlan'])+','
                            last_vlan = con2['vlan']
                        else:
                            last_vlan = None
                    actions += 'output=' + str(con2['input_port'])  +','

                #remove last coma
                actions = actions[:-1]
                
                flow['actions'] = actions

                result = self.rest_call(flow, "POST") 
                if result[0]!=200:
                    return -1, created_connections, "HTTP POST over '%s' return %d: %s" %(str(self.server)+":"+str(self.port), str(result[0]), str(result[1]) )
                created_connections[dpid]["end"] = index
        return index, created_connections, None          
    
    def disconnect(self, list_of_flows_to_remove, switch_dpid):
        deleted=0
        for flow_name in list_of_flows_to_remove:
                flow = {"switch": switch_dpid, "name": flow_name }
                result = self.rest_call(flow, "DELETE")
                if result[0]!=200:
                    return -1, {}, "HTTP DEELTE over '%s' return %d: %s" %(str(self.server)+":"+str(self.port), str(result[0]), str(result[1]) )
                    #TODO: return only the items not deleted
                deleted += 1
        return deleted, {}, None           
            
