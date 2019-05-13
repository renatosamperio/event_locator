#!/usr/bin/env python

import sys, os
import threading
import rospy
import Queue
import datetime

from optparse import OptionParser, OptionGroup
from pprint import pprint
from collections import OrderedDict

from hs_utils import ros_node, logging_utils
from hs_utils import slack_client
from hs_utils.mongo_handler import MongoAccess
from events_msgs.msg import WeeklyEvents
# from hs_utils import message_converter as mc
# from hs_utils import json_message_converter as rj

class SlackInformer(ros_node.RosNode):
    def __init__(self, **kwargs):
        try:
            
            ## Use lock to protect list elements from
            ##    corruption while concurrently access. 
            ##    Check Global Interpreter Lock (GIL)
            ##    for more information
            self.threats_lock           = threading.Lock()
            
            ## This variable has to be started before ROS
            ##   params are called
            self.condition              = threading.Condition()
            self.message_stack          = Queue.Queue()

            ## Initialising parent class with all ROS stuff
            super(SlackInformer, self).__init__(**kwargs)
            
            self.slack_client     = None
            
            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)

    def SubscribeCallback(self, msg, topic):
        try:
            with self.threats_lock:
                self.message_stack.put(msg)

            ## Notify thread that data has arrived
            with self.condition:
                self.condition.notifyAll()
            
        except Exception as inst:
              ros_node.ParseException(inst)
      
    def Init(self):
        try:
            
            self.spotify_icon       = "https://cdn2.iconfinder.com/data/icons/social-icons-33/128/Spotify-512.png"
            self.musixmatch_icon    = "https://pbs.twimg.com/profile_images/875662230972399617/lcqEXGrR.jpg"
            
            try:
                self.slack_channel      = os.environ['SLACK_CHANNEL']
            except KeyError:
                rospy.logerr("Invalid slack channel")
                rospy.signal_shutdown("Invalid slack channel")
                
            slack_token             = os.environ['SLACK_TOKEN']
            
            if not slack_token.startswith('xoxp'):
                rospy.logerr("Invalid slack token [%s]"%slack_token)
                rospy.signal_shutdown("Invalid slack token")
            
            rospy.logdebug("Got slack token and chanel")
            self.slack_client = slack_client.SlackHandler(slack_token)
            rospy.Timer(rospy.Duration(1.0), self.Run, oneshot=True)
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def ShutdownCallback(self):
        try:
            rospy.logdebug('+ Shutdown: Doing nothing...')
        except Exception as inst:
              ros_node.ParseException(inst)

    def GetSpotifyFields(self, spotify):
        fields      = []
        text        = ''
        try:
            #pprint(spotify)
            item   = {
                "title": "Popularity",
                "value": spotify.popularity,
                "short": True
            }
            fields.append(item)
            
            item   = {
                "title": "Followers",
                "value": spotify.followers,
                "short": True
            }
            fields.append(item)
            
            if spotify.similarity_score<1.0:
                item   = {
                    "title": "Similarity",
                    "value": spotify.similarity_score,
                    "short": True
                }
                fields.append(item)
            
            genres_size = len(spotify.genres)
            if genres_size>1:
                label = ''
                for i in range(genres_size):
                    genre = spotify.genres[i]
                    label += genre
                    if i != (genres_size-1):
                        label += ', '
                item   = {
                    "title": "Genres",
                    "value": label,
                    "short": True
                }
                fields.append(item)
            
            if len(spotify.top_tracks)>0:
                for track in spotify.top_tracks:
                    song_name   = track.song_name
                    album_name  = track.album_name
                    text += (song_name+' - '+album_name)+'\n'
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return text, fields
    
    def GetVenueFields(self, fields, event, city):
        try:
            if event.venue.id != "":
                label  = event.venue.name
                if event.venue.website != "":
                    label = "<"+event.venue.website+"|"+label+">"
                    
                item   = {
                    "title": "Venue",
                    "value": label,
                    "short": True
                }
                fields.append(item)
                
            if event.venue.street != "":
                address = event.venue.street+", "+event.venue.zip+" "+city
                item   = {
                    "title": "Address",
                    "value": address,
                    "short": True
                }
                fields.append(item)
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return fields

    def GetTopTracks(self, spotify):
        items = []
        try:
            track_size = len(spotify.top_tracks)
            if track_size >0:
                attachment  = {}
                text        = "Top 10 songs for "+spotify.name 
                song        = spotify.top_tracks[0].song_name
                album       = spotify.top_tracks[0].album_name
                if len(spotify.top_tracks[0].preview_url)>0:
                    song    = "<"+spotify.top_tracks[0].preview_url+"|"+song+">"
                    album   = "<"+spotify.top_tracks[0].preview_url+"|"+album+">"
#                 else:
#                     print "===> spotify"
#                     pprint(spotify)
                
                attachment["text"] = text
                fields  = [
                    {
                         "title": "Song",
                         "value": song,
                         "short": True
                    },
                    {
                         "title": "Album",
                         "value": album,
                         "short": True
                    }
                ]

                attachment["fields"] = fields
                
                for i in range(track_size)[1:]:
                    track   = spotify.top_tracks[i]
                    song    = track.song_name
                    album   = track.album_name
                    if len(track.preview_url)>0:
                        song    = "<"+track.preview_url+"|"+song+">"
                        album   = "<"+track.preview_url+"|"+album+">"
                    
                    song    = {
                        "value": song,
                        "short": True
                    }
                    attachment["fields"].append(song)
                    album = {
                        "value": album,
                        "short": True
                    }
                    attachment["fields"].append(album)
                items.append(attachment)
                
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return items
        
    def Run(self, event):
        ''' Run method '''
        try:
            rospy.logdebug('+ Running slack informer')
            
            ## This sample produces calls every 250 ms (40Hz), 
            ##    however we are interested in time passing
            ##    by seconds
            while not rospy.is_shutdown():
                
                todays_date = datetime.datetime.now().strftime("%A %d %B, %Y")
                while not self.message_stack.empty():
                    ## Collecting messages
                    with self.threats_lock:
                        events = self.message_stack.get()

                    rospy.logdebug("+ Events from %s to %s in %s, %s"%
                            (events.start_date, events.end_date, 
                             events.city, events.country))
                    attachement = []
                    for event in events.events:
                        
                        ## 1) Do not show spotify if similarity is not 1.0
                        ## 2) Display information of 2 artists! with two attachments
                        if event.status != 'ok':
                            rospy.loginfo('Event %s is [%s]'%(msg.name, msg.status))
                            continue
                             
                        if event.hasEnded:
                            rospy.loginfo('Event %s has ended'%(msg.name))
                            continue
                        
                        author_name     = ''
                        author_icon     = ''
                        title_link      = ''
                        image_url       = ''
                        footer          = ''
                        footer_icon     = ''
                        fields          = []
                        if len(event.artist.spotify.id)<1:
                            rospy.logdebug('   No spotify information found for %s'%(event.artist.name))
                            pprint(event)
                        else:
                            ## Collecting spotify data
                            spotify     = event.artist.spotify
                            footer_icon = self.spotify_icon
                            footer      = 'Spotify'
                            image_url   = spotify.image.url
                            
                            artis_id    = spotify.uri.split(':')[2]
                            title_link  = 'https://open.spotify.com/artist/'+artis_id
                            text, fields= self.GetSpotifyFields(spotify)
                            
                        ## Collect venue info
                        fields          = self.GetVenueFields(fields, event, events.city)
                            
                        if len(event.artist.musix_match)<1:
                            rospy.logdebug('   No musix match information found for %s'%(event.artist.name))
                         
                        rospy.logdebug("   Collecting information from %s"%(event.name))
                        attachement.append({ 
                            "title":        event.name,
                            "title_link":   title_link,
                            "image_url":    image_url,
                              
# #                             "author_name": "Lime Torrents Crawler",
# #                             "author_icon":  author_icon,
# #                             "author_link":  author_name,
#                               
# #                             "text":         text,
                            "pretext":      todays_date,
                               
                            "footer":       footer,
                            "footer_icon":  footer_icon,
      
                            "fields":       fields,
                        })
                        
                        top_tracks = self.GetTopTracks(spotify)
                        if len(top_tracks)>0:
                            attachement = attachement + top_tracks
                        
                        ## Publishing slack message
                        response = self.slack_client.PostMessage(
                            self.slack_channel, "",
                            username='',
                            icon_emoji='',
                            as_user=True,
                            attachments=attachement
                        )
                        if not response['ok'] :
                            pprint(response)
            
                ## Waiting for more messages
                with self.condition:
                    rospy.logdebug('+ Waiting for more events to announce')
                    self.condition.wait()
        except Exception as inst:
              ros_node.ParseException(inst)


if __name__ == '__main__':
    usage       = "usage: %prog option1=string option2=bool"
    parser      = OptionParser(usage=usage)
    parser.add_option('--queue_size',
                type="int",
                action='store',
                default=1000,
                help='Topics to play')
    parser.add_option('--latch',
                action='store_true',
                default=False,
                help='Message latching')
    parser.add_option('--debug',
                action='store_true',
                default=False,
                help='Provide debug level')
    parser.add_option('--syslog',
                action='store_true',
                default=False,
                help='Start with syslog logger')

    (options, args) = parser.parse_args()
    
    args            = {}
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('slack_informer', anonymous=False, log_level=logLevel)
    
    ## Sending logging to syslog
    if options.syslog:
        logging_utils.update_loggers()

    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('/event_locator/updated_events',  WeeklyEvents),
    ]
    pub_topics     = [
#         ('/event_locator/updated_events', WeeklyEvents)
    ]
    system_params  = [
        #'/event_locator_param'
    ]
    
    ## Defining arguments
    args.update({'queue_size':      options.queue_size})
    args.update({'latch':           options.latch})
    args.update({'sub_topics':      sub_topics})
    args.update({'pub_topics':      pub_topics})
    #args.update({'system_params':   system_params})
    
    # Go to class functions that do all the heavy lifting.
    try:
        spinner = SlackInformer(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()

