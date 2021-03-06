# freeseer - vga/presentation capture software
#
#  Copyright (C) 2011, 2013  Free and Open Source Software Learning Centre
#  http://fosslc.org
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# For support, questions, suggestions or any other inquiries, visit:
# http://github.com/Freeseer/freeseer/


'''
RTMP streaming
--------------

The `Real Time Messaging Protocol (RTMP) <http://en.wikipedia.org/wiki/Real_Time_Messaging_Protocol>`_
is a popular format for video/audio streaming. You can stream from Freeseer
to an arbitrary server using the RTMP plugin.

To enable streaming

1. Open :ref:`Freeseer's configuration <config>` and go to the "Recording" tab
2. Check the "Record to Stream" box
3. Set the stream format to "RTMP Streaming"
4. Click the "Setup" button to access more options
5. Specify the "Stream URL" (the location you'll be streaming to)

.. note:: All outputs must be set to "leaky mode".
          Go to "Plugins" > "Output" > "Video Preview" > "Leaky Queue".

Justin.tv
*********

There is built-in support for streaming to `Justin.tv <http://www.justin.tv/>`_.
To enable it, repeat the above steps 1-4, then change the
"Streaming Destination" from "custom" to "justin.tv".

You also have to input your "Streaming Key".
To get one, `log in to your Justin.tv account <http://www.justin.tv/user/login>`_
and go to http://www.justin.tv/broadcast/adv_other.

You also have the option to set your Justin.tv channel properties (stream title
and description). Check the "Set Justin.tv channel properties" box and enter
your "Consumer Key" and "Consumer Secret".

.. tip::
  To obtain a Consumer Key and Consumer Secret from Justin.tv,
  got to http://www.twitch.tv/developer/activate.

  You will need to provide login credentials for Justin.tv.
  This will make your account a developer account (as of this moment,
  this does not have any adverse effects).

  In order to obtain the Consumer Key and Consumer Secret,
  you will have to create an application in Justin.tv.
  To do this, go to http://www.twitch.tv/oauth_clients/create.

  On this page you will be asked to provide a name for the application and
  a set of URLs - these can be chosen arbitrarily, they serve no purpose for
  RTMP streaming. After you press "Save", you will be taken to a page where the
  Consumer Key and Consumer Secret will be shown - you can now provide
  these to Freeseer!

When you're done setting up your Justin.tv preferences in Freeseer, click the
"Apply - stream to Justin.tv" button on the bottom of the settings tab. Enjoy!

@author: Jonathan Shen
'''

# Python libs
import logging
import pickle
import webbrowser

# GStreamer libs
import pygst
pygst.require("0.10")
import gst

# Qt libs
from PyQt4 import QtGui, QtCore

# Freeseer libs
from freeseer.framework.plugin import IOutput
from freeseer.framework.plugin import PluginError
from freeseer.framework.config import Config, options

log = logging.getLogger(__name__)

#
# Non-standard imports required for plugin but not
# for freeseer to run.
#
try:
    import httplib
    import simplejson
    from oauth import oauth
except:
    log.error("""RTMP-Streaming: Failed to load plugin.
        This plugin requires the following libraries in order operate:

            - httplib
            - simplejson
            - oauth

        If you wish to use this plugin please ensure these libraries are installed on your system.
        """)
    raise PluginError("Plugin missing required dependencies.")

TUNE_VALUES = ['none', 'film', 'animation', 'grain', 'stillimage', 'psnr', 'ssim', 'fastdecode', 'zerolatency']
AUDIO_CODEC_VALUES = ['lame', 'faac']
STREAMING_DESTINATION_VALUES = ['custom', 'justin.tv']
JUSTIN_URL = 'rtmp://live-3c.justin.tv/app/'
STATUS_KEYS = ['artist', 'title']
DESCRIPTION_KEY = 'comment'


class RTMPOutputConfig(Config):
    """Configuration class for RTMPOut plugin."""
    url = options.StringOption('')
    audio_quality = options.IntegerOption(3)
    video_bitrate = options.IntegerOption(2400)
    video_tune = options.ChoiceOption(TUNE_VALUES, 'none')
    audio_codec = options.ChoiceOption(AUDIO_CODEC_VALUES, 'lame')
    streaming_destination = options.ChoiceOption(STREAMING_DESTINATION_VALUES, 'custom')
    streaming_key = options.StringOption('')
    consumer_key = options.StringOption('')
    consumer_secret = options.StringOption('')
    authorization_url = options.StringOption('')
    use_justin_api = options.StringOption('no')
    justin_api_persistent = options.StringOption('')


class RTMPOutput(IOutput):
    name = "RTMP Streaming"
    os = ["linux", "linux2", "win32", "cygwin"]
    type = IOutput.BOTH
    recordto = IOutput.STREAM
    tags = None
    justin_api = None
    streaming_destination_widget = None
    load_config_delegate = None
    CONFIG_CLASS = RTMPOutputConfig

    #@brief - RTMP Streaming plugin.
    # Structure for function was based primarily off the ogg function
    # Creates a bin to stream flv content to [self.config.url]
    # Bin has audio and video ghost sink pads
    # Converts audio and video to flv with [flvmux] element
    # Streams flv content to [self.config.url]
    # TODO - Error handling - verify pad setup
    def get_output_bin(self, audio=True, video=True, metadata=None):
        bin = gst.Bin()

        if metadata is not None:
            self.set_metadata(metadata)

        # Muxer
        muxer = gst.element_factory_make("flvmux", "muxer")

        # Setup metadata
        # set tag merge mode to GST_TAG_MERGE_REPLACE
        merge_mode = gst.TagMergeMode.__enum_values__[2]

        if metadata is not None:
            # Only set tag if metadata is set
            muxer.merge_tags(self.tags, merge_mode)
        muxer.set_tag_merge_mode(merge_mode)

        bin.add(muxer)

        # RTMP sink
        rtmpsink = gst.element_factory_make('rtmpsink', 'rtmpsink')
        rtmpsink.set_property('location', self.config.url)
        bin.add(rtmpsink)

        #
        # Setup Audio Pipeline if Audio Recording is Enabled
        #
        if audio:
            audioqueue = gst.element_factory_make("queue", "audioqueue")
            bin.add(audioqueue)

            audioconvert = gst.element_factory_make("audioconvert", "audioconvert")
            bin.add(audioconvert)

            audiolevel = gst.element_factory_make('level', 'audiolevel')
            audiolevel.set_property('interval', 20000000)
            bin.add(audiolevel)

            audiocodec = gst.element_factory_make(self.config.audio_codec, "audiocodec")

            if 'quality' in audiocodec.get_property_names():
                audiocodec.set_property("quality", self.config.audio_quality)
            else:
                log.debug("WARNING: Missing property: 'quality' on audiocodec; available: " +
                    ','.join(audiocodec.get_property_names()))
            bin.add(audiocodec)

            # Setup ghost pads
            audiopad = audioqueue.get_pad("sink")
            audio_ghostpad = gst.GhostPad("audiosink", audiopad)
            bin.add_pad(audio_ghostpad)

            # Link Elements
            audioqueue.link(audioconvert)
            audioconvert.link(audiolevel)
            audiolevel.link(audiocodec)
            audiocodec.link(muxer)

        #
        # Setup Video Pipeline
        #
        if video:
            videoqueue = gst.element_factory_make("queue", "videoqueue")
            bin.add(videoqueue)

            videocodec = gst.element_factory_make("x264enc", "videocodec")
            videocodec.set_property("bitrate", self.config.video_bitrate)
            if self.config.video_tune != 'none':
                videocodec.set_property('tune', self.config.video_tune)
            bin.add(videocodec)

            # Setup ghost pads
            videopad = videoqueue.get_pad("sink")
            video_ghostpad = gst.GhostPad("videosink", videopad)
            bin.add_pad(video_ghostpad)

            # Link Elements
            videoqueue.link(videocodec)
            videocodec.link(muxer)

        #
        # Link muxer to rtmpsink
        #
        muxer.link(rtmpsink)

        if self.config.streaming_destination == STREAMING_DESTINATION_VALUES[1] and self.config.use_justin_api == 'yes':
            self.justin_api.set_channel_status(self.get_talk_status(metadata),
                                               self.get_description(metadata))

        return bin

    def get_talk_status(self, metadata):
        if not metadata:
            return ""
        return " - ".join([metadata[status_key] for status_key in self.STATUS_KEYS])

    def get_description(self, metadata):
        if not metadata:
            return ""
        return metadata[self.DESCRIPTION_KEY]

    def set_metadata(self, data):
        '''
        Populate global tag list variable with file metadata for
        vorbistag audio element
        '''
        self.tags = gst.TagList()

        for tag in data.keys():
            if(gst.tag_exists(tag)):
                self.tags[tag] = data[tag]
            else:
                #self.core.logger.log.debug("WARNING: Tag \"" + str(tag) + "\" is not registered with gstreamer.")
                pass

    def load_config(self, plugman, config=None):
        super(RTMPOutput, self).load_config(plugman)
        if self.config.justin_api_persistent:
            self.justin_api = JustinApi.from_string(self.config.justin_api_persistent)
            self.justin_api.set_save_method(self.set_justin_api_persistent)

    def get_stream_settings_widget(self):
        self.stream_settings_widget = QtGui.QWidget()
        self.stream_settings_widget_layout = QtGui.QFormLayout()
        self.stream_settings_widget.setLayout(self.stream_settings_widget_layout)
        #
        # Stream URL
        #

        # TODO: URL validation?

        self.label_stream_url = QtGui.QLabel("Stream URL")
        self.lineedit_stream_url = QtGui.QLineEdit()
        self.stream_settings_widget_layout.addRow(self.label_stream_url, self.lineedit_stream_url)

        self.lineedit_stream_url.textEdited.connect(self.set_stream_url)

        #
        # Audio Quality
        #

        self.label_audio_quality = QtGui.QLabel("Audio Quality")
        self.spinbox_audio_quality = QtGui.QSpinBox()
        self.spinbox_audio_quality.setMinimum(0)
        self.spinbox_audio_quality.setMaximum(9)
        self.spinbox_audio_quality.setSingleStep(1)
        self.spinbox_audio_quality.setValue(5)
        self.stream_settings_widget_layout.addRow(self.label_audio_quality, self.spinbox_audio_quality)

        self.stream_settings_widget.connect(self.spinbox_audio_quality, QtCore.SIGNAL('valueChanged(int)'), self.set_audio_quality)

        #
        # Audio Codec
        #

        self.label_audio_codec = QtGui.QLabel("Audio Codec")
        self.combobox_audio_codec = QtGui.QComboBox()
        self.combobox_audio_codec.addItems(AUDIO_CODEC_VALUES)
        self.stream_settings_widget_layout.addRow(self.label_audio_codec, self.combobox_audio_codec)

        self.stream_settings_widget.connect(self.combobox_audio_codec,
                                            QtCore.SIGNAL('currentIndexChanged(const QString&)'),
                                            self.set_audio_codec)

        #
        # Video Quality
        #

        self.label_video_quality = QtGui.QLabel("Video Quality (kb/s)")
        self.spinbox_video_quality = QtGui.QSpinBox()
        self.spinbox_video_quality.setMinimum(0)
        self.spinbox_video_quality.setMaximum(16777215)
        self.spinbox_video_quality.setValue(2400)           # Default value 2400
        self.stream_settings_widget_layout.addRow(self.label_video_quality, self.spinbox_video_quality)

        self.stream_settings_widget.connect(self.spinbox_video_quality, QtCore.SIGNAL('valueChanged(int)'), self.set_video_bitrate)

        #
        # Video Tune
        #

        self.label_video_tune = QtGui.QLabel("Video Tune")
        self.combobox_video_tune = QtGui.QComboBox()
        self.combobox_video_tune.addItems(TUNE_VALUES)
        self.stream_settings_widget_layout.addRow(self.label_video_tune, self.combobox_video_tune)

        self.stream_settings_widget.connect(self.combobox_video_tune,
                                            QtCore.SIGNAL('currentIndexChanged(const QString&)'),
                                            self.set_video_tune)

        #
        # Note
        #

        self.label_note = QtGui.QLabel(self.gui.uiTranslator.translate('rtmp', "*For RTMP streaming, all other outputs must be set to leaky"))
        self.stream_settings_widget_layout.addRow(self.label_note)

        return self.stream_settings_widget

    def setup_streaming_destination_widget(self, streaming_dest):
        if streaming_dest == STREAMING_DESTINATION_VALUES[0]:
            self.load_config_delegate = None
            self.unlock_stream_settings()
            return None
        if streaming_dest == STREAMING_DESTINATION_VALUES[1]:
            self.load_config_delegate = self.justin_widget_load_config
            self.lineedit_stream_url.setEnabled(False)
            self.combobox_audio_codec.setEnabled(False)
            return self.get_justin_widget()

    def get_justin_widget(self):
        self.justin_widget = QtGui.QWidget()
        self.justin_widget_layout = QtGui.QFormLayout()
        self.justin_widget.setLayout(self.justin_widget_layout)

        #
        # justin.tv Streaming Key
        #

        self.label_streaming_key = QtGui.QLabel("Streaming Key")
        self.lineedit_streaming_key = QtGui.QLineEdit()
        self.justin_widget_layout.addRow(self.label_streaming_key, self.lineedit_streaming_key)

        self.lineedit_streaming_key.textEdited.connect(self.set_streaming_key)

        #
        # Note
        #

        self.label_note = QtGui.QLabel(self.gui.uiTranslator.translate('rtmp', "*See: http://www.justin.tv/broadcast/adv_other\n" +
                                                                       "You must be logged in to obtain your Streaming Key"))
        self.justin_widget_layout.addRow(self.label_note)

        #
        # Checkbox for whether or not to use the justin.tv API to push channel settings
        #

        self.label_api_checkbox = QtGui.QLabel("Set Justin.tv channel properties")
        self.api_checkbox = QtGui.QCheckBox()
        self.justin_widget_layout.addRow(self.label_api_checkbox, self.api_checkbox)

        self.api_checkbox.stateChanged.connect(self.set_use_justin_api)

        #
        # Consumer key
        #

        self.label_consumer_key = QtGui.QLabel("Consumer Key (optional)")
        self.lineedit_consumer_key = QtGui.QLineEdit()
        self.justin_widget_layout.addRow(self.label_consumer_key, self.lineedit_consumer_key)

        self.lineedit_consumer_key.textEdited.connect(self.set_consumer_key)

        #
        # Consumer secret
        #

        self.label_consumer_secret = QtGui.QLabel("Consumer Secret (optional)")
        self.lineedit_consumer_secret = QtGui.QLineEdit()
        self.justin_widget_layout.addRow(self.label_consumer_secret, self.lineedit_consumer_secret)

        self.lineedit_consumer_secret.textEdited.connect(self.set_consumer_secret)

        #
        # Apply button, so as not to accidentally overwrite custom settings
        #

        self.apply_button = QtGui.QPushButton("Apply - stream to Justin.tv")
        self.apply_button.setToolTip(self.gui.uiTranslator.translate('rtmp', "Overwrite custom settings for justin.tv"))
        self.justin_widget_layout.addRow(self.apply_button)

        self.apply_button.clicked.connect(self.apply_justin_settings)

        return self.justin_widget

    def get_widget(self):
        if self.widget is None:
            self.widget = QtGui.QWidget()
            self.widget.setWindowTitle("RTMP Streaming Options")

            self.widget_layout = QtGui.QFormLayout()
            self.widget.setLayout(self.widget_layout)

            #
            # Streaming presets
            #

            self.stream_settings_area = QtGui.QScrollArea()
            self.stream_settings_area.setWidgetResizable(True)
            self.widget_layout.addRow(self.stream_settings_area)

            self.stream_settings_area.setWidget(self.get_stream_settings_widget())

            self.label_streaming_dest = QtGui.QLabel("Streaming Destination")
            self.combobox_streaming_dest = QtGui.QComboBox()
            self.combobox_streaming_dest.addItems(STREAMING_DESTINATION_VALUES)

            self.widget_layout.addRow(self.label_streaming_dest, self.combobox_streaming_dest)

            self.widget.connect(self.combobox_streaming_dest,
                                QtCore.SIGNAL('currentIndexChanged(const QString&)'),
                                self.set_streaming_dest)

        return self.widget

    def load_streaming_destination_widget(self):
        streaming_destination_widget = self.setup_streaming_destination_widget(self.config.streaming_destination)

        if self.streaming_destination_widget is not None:
            self.streaming_destination_widget.deleteLater()
            self.streaming_destination_widget = None

        if streaming_destination_widget:
            self.widget_layout.addRow(streaming_destination_widget)
            self.streaming_destination_widget = streaming_destination_widget

    def widget_load_config(self, plugman):
        self.load_config(plugman)
        self.stream_settings_load_config()

        self.combobox_streaming_dest.setCurrentIndex(STREAMING_DESTINATION_VALUES.index(self.config.streaming_destination))

        self.load_streaming_destination_widget()
        if self.load_config_delegate:
            self.load_config_delegate()

    def justin_widget_load_config(self):
        self.lineedit_streaming_key.setText(self.config.streaming_key)
        self.lineedit_consumer_key.setText(self.config.consumer_key)
        self.lineedit_consumer_secret.setText(self.config.consumer_secret)

        check_state = 0
        if self.config.use_justin_api == 'yes':
            check_state = 2
        self.api_checkbox.setCheckState(check_state)
        self.toggle_consumer_key_secret_fields()

    def unlock_stream_settings(self):
        self.lineedit_stream_url.setEnabled(True)
        self.spinbox_audio_quality.setEnabled(True)
        self.spinbox_video_quality.setEnabled(True)
        self.combobox_video_tune.setEnabled(True)
        self.combobox_audio_codec.setEnabled(True)

    def stream_settings_load_config(self):
        self.lineedit_stream_url.setText(self.config.url)

        self.spinbox_audio_quality.setValue(self.config.audio_quality)
        self.spinbox_video_quality.setValue(self.config.video_bitrate)

        tuneIndex = self.combobox_video_tune.findText(self.config.video_tune)
        self.combobox_video_tune.setCurrentIndex(tuneIndex)

        acIndex = self.combobox_audio_codec.findText(self.config.audio_codec)
        self.combobox_audio_codec.setCurrentIndex(acIndex)

    def set_stream_url(self, text):
        self.config.url = text
        self.config.save()

    def set_audio_quality(self):
        self.config.audio_quality = self.spinbox_audio_quality.value()
        self.config.save()

    def set_video_bitrate(self):
        self.config.video_bitrate = self.spinbox_video_quality.value()
        self.config.save()

    def set_video_tune(self, tune):
        self.config.video_tune = tune
        self.config.save()

    def set_audio_codec(self, codec):
        self.config.audio_codec = codec
        self.config.save()

    def set_streaming_dest(self, dest):
        self.config.streaming_destination = dest

        if self.config.streaming_destination in STREAMING_DESTINATION_VALUES:
            index = min([i for i in range(len(STREAMING_DESTINATION_VALUES))
                if STREAMING_DESTINATION_VALUES[i] == self.config.streaming_destination])
            self.combobox_streaming_dest.setCurrentIndex(index)

        self.load_streaming_destination_widget()
        if self.load_config_delegate:
            self.load_config_delegate()
        self.config.save()

    def set_streaming_key(self, text):
        self.config.streaming_key = str(text)
        self.config.save()

    def set_use_justin_api(self, state):
        if state != 0:
            self.config.use_justin_api = 'yes'
        else:
            self.config.use_justin_api = 'no'
        self.config.save()
        self.toggle_consumer_key_secret_fields()

    def toggle_consumer_key_secret_fields(self):
        if self.config.use_justin_api == 'yes':
            self.lineedit_consumer_key.setEnabled(True)
            self.lineedit_consumer_secret.setEnabled(True)
        else:
            self.lineedit_consumer_key.setEnabled(False)
            self.lineedit_consumer_secret.setEnabled(False)

    def set_consumer_key(self, text):
        self.config.consumer_key = str(text)
        self.config.save()

    def set_consumer_secret(self, text):
        self.config.consumer_secret = str(text)
        self.config.save()

    def set_justin_api_persistent(self, text):
        self.justin_api_persistent = str(text)
        self.config.save()

    def apply_justin_settings(self):
        # here is where all the justin.tv streaming presets will be applied
        self.set_stream_url(self.JUSTIN_URL + self.config.streaming_key)
        self.set_audio_codec('lame')

        self.stream_settings_load_config()

        try:
            if self.config.consumer_key and self.config.consumer_secret:
                url, self.justin_api = JustinApi.open_request(self.config.consumer_key, self.config.consumer_secret)
                self.justin_api.set_save_method(self.set_justin_api_persistent)
                webbrowser.open(url)
                QtGui.QMessageBox.information(self.widget,
                    "justin.tv authentication",
                    self.gui.uiTranslator.translate('rtmp', "An authorization URL should have opened in your browser.\n"
                        "If not, go open the following URL to allow freeseer to manage your justin.tv channel.\n"
                        "%1").arg(url),
                    QtGui.QMessageBox.Ok,
                    QtGui.QMessageBox.Ok)
        except KeyError:
            log.error("justin.tv API error: Authentication failed. Supplied credentials may be incorrect.")
            QtGui.QMessageBox.critical(self.widget,
                "justin.tv error",
                self.gui.uiTranslator.translate('rtmp', "Authentication failed. Supplied credentials for Justin.tv"
                    " may be incorrect."),
                QtGui.QMessageBox.Ok,
                QtGui.QMessageBox.Ok)


class JustinApi:
    addr = 'api.justin.tv'

    @staticmethod
    def open_request(consumer_key, consumer_secret):
        """
        returns request url and JustinClient object
        the object will need to obtain access token on first use
        """
        consumer = oauth.OAuthConsumer(consumer_key, consumer_secret)
        url = "http://%s/oauth/request_token" % JustinApi.addr
        request = oauth.OAuthRequest.from_consumer_and_token(
            consumer,
            None,
            http_method='GET',
            http_url=url)

        request.sign_request(oauth.OAuthSignatureMethod_HMAC_SHA1(), consumer, None)

        connection = httplib.HTTPConnection(JustinApi.addr)
        connection.request('GET', request.http_url, headers=request.to_header())
        result = connection.getresponse().read()

        token = oauth.OAuthToken.from_string(result)

        auth_request = oauth.OAuthRequest.from_token_and_callback(
            token=token,
            callback='http://localhost/',
            http_url='http://%s/oauth/authorize' % JustinApi.addr)

        return auth_request.to_url(), JustinApi(consumer_key=consumer_key, consumer_secret=consumer_secret, request_token_str=result)

    @staticmethod
    def from_string(persistent_obj):
        """
        Returns JustinClient object from string.
        """
        consumer_key, consumer_secret, request_token_str, access_token_str = pickle.loads(persistent_obj)
        return JustinApi(consumer_key, consumer_secret, request_token_str, access_token_str)

    def __init__(self, consumer_key="", consumer_secret="", request_token_str="", access_token_str=""):
        self.config.consumer_key = consumer_key
        self.config.consumer_secret = consumer_secret
        self.request_token_str = request_token_str
        self.access_token_str = access_token_str

    def set_save_method(self, save_method):
        """
        upon obtaining an access token, this object will be have a different
        serialization

        in order to support this the given save_method should be called
        upon any such change with the new serialization as its only argument
        """
        self.save_method = save_method
        self.save_method(self.to_string())

    def obtain_access_token(self):
        try:
            consumer = oauth.OAuthConsumer(self.config.consumer_key, self.config.consumer_secret)
            token = oauth.OAuthToken.from_string(self.request_token_str)
            url = "http://%s/oauth/access_token" % JustinApi.addr
            request = oauth.OAuthRequest.from_consumer_and_token(
                consumer,
                token,
                http_method='GET',
                http_url=url)
            request.sign_request(oauth.OAuthSignatureMethod_HMAC_SHA1(), consumer, token)
            connection = httplib.HTTPConnection(self.addr)
            connection.request('GET', request.http_url, headers=request.to_header())
            result = connection.getresponse().read()
            self.access_token_str = result
            oauth.OAuthToken.from_string(result)
            self.save_method(self.to_string())
        except KeyError:
            log.error("justin.tv API: failed to obtain an access token")

    def get_data(self, endpoint):
        try:
            token = oauth.OAuthToken.from_string(self.access_token_str)
            consumer = oauth.OAuthConsumer(self.config.consumer_key, self.config.consumer_secret)
            request = oauth.OAuthRequest.from_consumer_and_token(
                consumer,
                token,
                http_method='GET',
                http_url="http://%s/api/%s" % (JustinApi.addr, endpoint))
            request.sign_request(oauth.OAuthSignatureMethod_HMAC_SHA1(), consumer, token)
            connection = httplib.HTTPConnection(self.addr)
            connection.request('GET', request.http_url, headers=request.to_header())
            result = connection.getresponse().read()
            data = simplejson.loads(result)
        except KeyError, simplejson.decoder.JSONDecodeError:
            log.error("justin.tv API: failed fetch data from endpoint %s" % endpoint)
            return dict()
        return data

    def set_data(self, endpoint, payload):
        try:
            token = oauth.OAuthToken.from_string(self.access_token_str)
            consumer = oauth.OAuthConsumer(self.config.consumer_key, self.config.consumer_secret)
            request = oauth.OAuthRequest.from_consumer_and_token(
                consumer,
                token,
                http_method='POST',
                http_url="http://%s/api/%s" % (JustinApi.addr, endpoint),
                parameters=payload)
            request.sign_request(oauth.OAuthSignatureMethod_HMAC_SHA1(), consumer, token)
            connection = httplib.HTTPConnection(self.addr)
            connection.request('POST', request.http_url, body=request.to_postdata())
            result = connection.getresponse().read()
        except KeyError:
            log.error("justin.tv API: failed write data to endpoint %s" % endpoint)
            return None
        return result

    def set_channel_status(self, status, description):
        if not self.access_token_str:
            self.obtain_access_token()
        data = self.get_data("account/whoami.json")
        if not data:
            return
        login = data['login']
        data = self.get_data('channel/show/%s.json' % login)
        update_contents = {
            'title': status,
            'status': status,
            'description': description,
        }
        self.set_data('channel/update.json', update_contents)

    def to_string(self):
        return pickle.dumps([self.config.consumer_key, self.config.consumer_secret, str(self.request_token_str), str(self.access_token_str)])
