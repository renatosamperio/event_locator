#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import time
import json
import requests

from hs_utils import ros_node
from pprint import pprint

class Finder(object):
    def __init__(self, **kwargs):
        try:
            self.location    = None
            self.page_number = None
            self.api_key     = None
            
            ## Generating instance of strategy
            for key, value in kwargs.iteritems():
                if "api_key" == key:
                    self.api_key = value
                elif "location" == key:
                    self.location = value
                elif "page_number" == key:
                    self.page_number = value

            rospy.logdebug("Creating Generic HTTP requester")
        except Exception as inst:
            ros_node.ParseException(inst)
    
    def request_call(self, url, data):
        result = None
        try:
            start_time      = time.time()
            response = requests.get(url, params = data)
            
            if response.status_code == 200:
                result = response.json()
            elif response.status_code == 400:
                content     =  json.loads(response._content)
                if content["resultsPage"]["status"] == "error":
                    error   = content["resultsPage"]["error"]["message"]
                    rospy.logwarn("Bad request: "+error)
                else:
                    rospy.logwarn("Bad request")
            else:
                rospy.logwarn("Request status [%d]: %s"%
                              (response.status_code, response.reason))
            
        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            elapsed_time    = time.time() - start_time
            return result, response.status_code, elapsed_time

    def search_events(self, date_=None, page_number_=None):
        ''' Search for events'''
        try:
            rospy.logdebug('+ search_events: Doing nothing...')
            
        except Exception as inst:
            ros_node.ParseException(inst)
        pass
    
    def search_all_events(self):
        ''' Searches for all events '''
        try:
            rospy.logdebug('+ search_all_events: Doing nothing...')
            
        except Exception as inst:
            ros_node.ParseException(inst)
