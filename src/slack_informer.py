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
from std_msgs.msg import Bool

class SlackInformer(ros_node.RosNode):
    def __init__(self, **kwargs):
        try:
            
            ## Use lock to protect list elements from
            ##    corruption while concurrently access. 
            ##    Check Global Interpreter Lock (GIL)
            ##    for more information
            self.threats_lock     = threading.Lock()
            
            ## This variable has to be started before ROS
            ##   params are called
            self.condition        = threading.Condition()
            self.slack_msg_ready  = threading.Condition()
            self.clean_channel    = threading.Condition()
            self.message_stack    = Queue.Queue()
            self.slack_bag        = Queue.Queue()

            ## Initialising parent class with all ROS stuff
            super(SlackInformer, self).__init__(**kwargs)
            self.slack_client     = None
            self.msg_id           = 0
            
            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)

    def SubscribeCallback(self, msg, topic):
        try:
            if topic == '/event_finder/updated_events':
                with self.threats_lock:
                    self.message_stack.put(msg)
    
                ## Notify thread that data has arrived
                with self.condition:
                    self.condition.notifyAll()
            elif topic == '/event_finder/clean_channel':
                
                if self.slack_channel is None:
                    return
                
                ## Notify thread that data has arrived
                rospy.logdebug("Received command to delete channel %s"%self.slack_channel)
                with self.clean_channel:
                    self.clean_channel.notifyAll()
                    
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
            
            rospy.logdebug("Got slack token and channel")
            self.slack_client = slack_client.SlackHandler(slack_token)
            rospy.Timer(rospy.Duration(0.3), self.Run,          oneshot=True)
            rospy.Timer(rospy.Duration(0.4), self.SlackPoster,  oneshot=True)
            rospy.Timer(rospy.Duration(0.5), self.CleanChannel,  oneshot=True)
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def ShutdownCallback(self):
        try:
            rospy.logdebug('+ Shutdown: Doing nothing...')
        except Exception as inst:
              ros_node.ParseException(inst)

    def GetSpotifyFields(self, spotify):
        fields      = []
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
            
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return fields
    
    def GetEventFields(self, fields, event, city):
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

            if event.start_time != "":
                start_time = event.start_time
                item   = {
                    "title": "Date",
                    "value": start_time,
                    "short": True
                }
                fields.append(item)

        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return fields

    def GetPerformanceFields(self, fields, performance):
        try:
            if performance.show_type != "":
                show_type = performance.show_type
                item   = {
                    "title": "Act",
                    "value": show_type,
                    "short": True
                }
                fields.append(item)
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return fields

    def PutMessage(self, element):
        '''
        Enqueue a slack message and inform that
        slack message is ready to go 
        '''
        try:
            ## Queue message
            self.msg_id += 1
            element = element+(self.msg_id,)
            rospy.logdebug('ADD: Adding item %d(%d) to slack message bag'%
                           (self.msg_id, len(element)))
            self.slack_bag.put(element)
            
            ## Notify thread that data has arrived
            with self.slack_msg_ready:
                self.slack_msg_ready.notifyAll()

        except Exception as inst:
              ros_node.ParseException(inst)

    def SlackPoster(self, event):
        '''
        Waits until message is ready and then posts it
        '''
        try:
            rospy.logdebug('ADD: Running slack message poster')
            wait_time = 1
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                with self.slack_msg_ready:
                    rospy.logdebug('ADD: Waiting for messages to post')
                    self.slack_msg_ready.wait()
                
                ## If it is here, is because someone 
                ##    put a message in the queue, so 
                ##    post everything that is queued
                while not self.slack_bag.empty():
                    
                    ## Get message from queue and post it in slack
                    try:
                        channel, text, attachment, msg_id = self.slack_bag.get()
                    except ValueError:
                        pprint()
                    rospy.logdebug('ADD: Posting message %d in slack channel [%s]'%
                                   (msg_id, self.slack_channel))
                    response = self.slack_client.PostMessage(
                        channel, text,
                        attachments=attachment
                    )
                    
                    ## Something went wrong in the posting
                    if not response['ok'] :
                        if response['error'] == 'ratelimited':
                            ## Put things back into queue but wait for a second...
                            rospy.loginfo('Slack messages are being posted too fast in channel %s'%self.slack_channel)
                            element = (channel, text, attachment, msg_id)
                            self.slack_bag.queue.appendleft(element)
                            rospy.logdebug('ADD:   waiting for %ds'%wait_time)
                            rospy.sleep(wait_time)
                        else:
                            ## We do not know what to do in other case
                            rospy.logwarn("ADD:   Slack posting went wrong...")
                            pprint(response)
                            
        except Exception as inst:
              ros_node.ParseException(inst)

    def CleanChannel(self, event):
        '''
        Waits until message is ready and then posts it
        '''
        try:
            rospy.logdebug('DEL: Running slack channel cleaner')
            wait_time = 1
            has_more = False
            rate_sleep = rospy.Rate(wait_time) 
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                with self.clean_channel:
                    rospy.logdebug('DEL: Waiting for channel to clean')
                    self.clean_channel.wait()
                
                retries         = 3
                channel_is_empty= False
                while not channel_is_empty:
                    rospy.loginfo('DEL: Deleting channel history')
                    response, channel_size = self.slack_client.DeleteChanngelHistory(self.slack_channel)
                    if response is None:
                        rospy.loginfo("DEL: No respose given")
                        break
                    response_items  = response.keys()
                    channel_is_empty= channel_size < 1
                    
                    ## API called may had failed
                    if response is None:
                        if retries>0:
                            rospy.logwarn("DEL: Invalid response, retrying after %ds"%waiting_time)
                            rospy.sleep(wait_time)
                            retries -= 1
                            continue
                        else:
                            rospy.logwarn("DEL: Invalid response, exiting")
                            break
                    
                    ## If response has not an OK someting weird happened
                    if 'ok' not in response.keys():
                        pprint(response)
                        rospy.logwarn("DEL: Missing response status")
                        break
                    
                    ## If response status was not OK, check whether the error is
                    ##    the slack server rate capabilities
                    if not response['ok']:
                        if response['error'] == 'ratelimited':
                            
                            ## Put things back into queue but wait for a second...
                            rospy.logdebug('DEL: Slack messages are being deleted too fast')
                            if not channel_is_empty: 
                    
                                ## Logging if there are more than 100 messages
                                rospy.logdebug('DEL:   waiting to remove %d messages'%(channel_size))
                                rospy.sleep(wait_time)
                        else:
                            ## Why the response was not ok?
                            rospy.logwarn("DEL: Failed reply %s"%response['error'])
                            pprint(response)
                    
        except Exception as inst:
              ros_node.ParseException(inst)

    def Run(self, event):
        ''' Run method '''
        try:
            rospy.logdebug('EVE: Running slack informer')
            
            ## Setting slack post constatns
            footer      = 'Spotify'
            footer_icon = self.spotify_icon

            ## Looping while messages are coming
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                with self.condition:
                    rospy.logdebug('EVE: Waiting for more events to announce')
                    self.condition.wait()
                    
                todays_date = datetime.datetime.now().strftime("%A %d %B, %Y")
                while not self.message_stack.empty():
                    ## Collecting messages
                    with self.threats_lock:
                        event = self.message_stack.get()

                    ## Getting general event information
                    rospy.loginfo("Got event from %s to %s in %s, %s"%
                            (event.start_date, event.end_date, 
                             event.city, event.country))
                    
                    concert      = event.concert
                    concert_name = concert.name
                    image_url   = ''
                    title_link  = ''
                    posted_main = False
                    
                    rospy.logdebug("EVE: Collecting information from %s"%(concert_name))
                    performances = event.concert.performance
                    
                    for i in range(len(performances)):
                        ## Getting performance data
                        performance = performances[i]
                        spotify     = performance.spotify
                        attachment = []
                        spotify_url = ''
                        rospy.logdebug("EVE: Preparing slack message for %s"%(performance.artist_name))
                        
                        ## Posting information about event
                        if not posted_main:
                            posted_main     = True
                            rospy.logdebug("EVE:   Queuing event information")
                            if len(spotify.image.url)>1:
                                image_url   = spotify.image.url
                            
                            ## Preparing message to post on-time
                            fields     = self.GetEventFields([], concert, event.city)
                            title_link = performance.artist_sk_uri
                            attachment.append({ 
                                "title":        concert_name,
                                "title_link":   title_link,
                                "image_url":    image_url,
                                "pretext":      todays_date,
                                "footer":       footer,
                                "footer_icon":  footer_icon,
                                "fields":       fields,
                            })
                            element     = (self.slack_channel, "", attachment)
                            self.PutMessage(element)
#                             response = self.slack_client.PostMessage(
#                                 self.slack_channel, "",
#                                 attachments=attachment
#                             )

                        ## Posting other acts in event
                        rospy.logdebug("EVE:   Queuing spotify act information for %s"%(performance.artist_name))
                        if len(spotify.uri)>1:
                            artis_id    = spotify.uri.split(':')[2]
                            spotify_url = 'https://open.spotify.com/artist/'+artis_id
                        
                        ## Preparing message in queue
                        fields      = self.GetSpotifyFields(spotify)
                        fields      = self.GetPerformanceFields(fields, performance)
                        attachment = [{"fields":       fields}]
                        text        = "*"+performance.artist_name+'*\n'+spotify_url
                        
                        ## Preparing message to post on-time
                        element = (self.slack_channel, text, attachment)
                        self.PutMessage(element)
#                         response = self.slack_client.PostMessage(
#                             self.slack_channel, text,
#                             attachments=attachment
#                         )
                    
        except Exception as inst:
              ros_node.ParseException(inst)
     
    def GetTopTracks(self, spotify):
        items = []
        try:
            if spotify is None:
                return

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
                   
    def Run2(self, event):
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
                    
                    #pprint(events)
                    
                    rospy.signal_shutdown("reason")
                    return
                    
                    for event in events.concert:
                        
                        ## 1) Do not show spotify if similarity is not 1.0
                        ## 2) Display information of 2 artists! with two attachments
                        if event.status != 'ok':
                            rospy.loginfo('Event %s is [%s]'%(msg.name, msg.status))
                            continue
                             
                        if event.hasEnded:
                            rospy.loginfo('Event %s has alread passed'%(msg.name))
                            continue
                        
                        author_name     = ''
                        author_icon     = ''
                        title_link      = ''
                        image_url       = ''
                        footer          = ''
                        spotify         = None
                        footer_icon     = ''
                        fields          = []
                        top_tracks      = []
                        if len(event.artist.spotify.id)<1:
                            rospy.logdebug('   No spotify information found for %s'%(event.artist.name))
                            #pprint(event)
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
                            fields          = self.GetEventFields(fields, event, events.city)
                                
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
                                "text":         title_link,
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
                                #error': 'ratelimited'
                                rospy.logwarn("%s"%ok['error'])
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
        ('/event_finder/updated_events', WeeklyEvents),
        ('/event_finder/clean_channel',  Bool),
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

