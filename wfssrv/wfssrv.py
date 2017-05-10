"""
This example demonstrates how to embed matplotlib WebAgg interactive
plotting in your own web application and framework.  It is not
necessary to do all this if you merely want to display a plot in a
browser or use matplotlib's built-in Tornado-based server "on the
side".

The framework being used must support web sockets.
"""

import io
import os

try:
    import tornado
except ImportError:
    raise RuntimeError("This example requires tornado.")
import tornado.web
import tornado.httpserver
import tornado.ioloop
import tornado.websocket


from matplotlib.backends.backend_webagg_core import (
    FigureManagerWebAgg, new_figure_manager_given_figure)
from matplotlib.figure import Figure

import numpy as np

import json

from mmtwfs.wfs import WFSFactory


class WFSServ(tornado.web.Application):
    class HomeHandler(tornado.web.RequestHandler):
        """
        Serves the main HTML page.
        """
        def get(self):
            self.render("home.html", current=self.application.wfs, wfslist=self.application.wfs_names)

    class SelectHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                wfs = self.get_argument("wfs")
                render = self.get_argument("render", default=False)
                if wfs in self.application.wfs_names:
                    print("setting %s" % wfs)
                    self.application.wfs = self.application.wfs_systems[wfs]
            except:
                print("Must specify valid wfs: %s." % wfs)

    class WFSPageHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                wfs = self.get_argument("wfs")
                if wfs in self.application.wfs_names:
                    print("setting %s" % wfs)
                    self.application.wfs = self.application.wfs_systems[wfs]
                    self.render("wfs.html", wfsname=self.application.wfs)
            except Exception as e:
                print("Must specify valid wfs: %s. %s" % (wfs, e))

    class ConnectHandler(tornado.web.RequestHandler):
        def get(self):
            if self.application.wfs is not None:
                if not self.application.wfs.connected:
                    self.application.wfs.connect()

    class DisconnectHandler(tornado.web.RequestHandler):
        def get(self):
            if self.application.wfs is not None:
                if self.application.wfs.connected:
                    self.application.wfs.disconnect()

    class AnalyzeHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                filename = self.get_argument("fitsfile")
                print(filename)
            except:
                print("no wfs or file specified.")

    class M1CorrectHandler(tornado.web.RequestHandler):
        def get(self):
            print("m1correct")

    class M2CorrectHandler(tornado.web.RequestHandler):
        def get(self):
            print("m2correct")

    class RecenterHandler(tornado.web.RequestHandler):
        def get(self):
            print("recenter")

    class RestartHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                wfs = self.get_argument('wfs')
                print("restarting %s" % wfs)
            except:
                print("no wfs specified")

    class DataDirHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                datadir = self.get_argument("datadir")
                print(datadir)
            except:
                print("no datadir specified")

    class M1GainHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                gain = float(self.get_argument(gain))
                for k, w in self.application.wfs_systems.items():
                    print("seeing m1_gain to %f in %s" % (gain, k))
            except:
                print("no m1_gain specified")

    class M2GainHandler(tornado.web.RequestHandler):
        def get(self):
            try:
                gain = float(self.get_argument(gain))
                for k, w in self.application.wfs_systems.items():
                    print("seeing m2_gain to %f in %s" % (gain, k))
            except:
                print("no m2_gain specified")

    class MplJs(tornado.web.RequestHandler):
        """
        Serves the generated matplotlib javascript file.  The content
        is dynamically generated based on which toolbar functions the
        user has defined.  Call `FigureManagerWebAgg` to get its
        content.
        """
        def get(self):
            self.set_header('Content-Type', 'application/javascript')

            js_content = FigureManagerWebAgg.get_javascript()

            self.write(js_content)

    class Download(tornado.web.RequestHandler):
        """
        Handles downloading of the figure in various file formats.
        """
        def get(self, fmt):
            managers = self.application.managers

            mimetypes = {
                'ps': 'application/postscript',
                'eps': 'application/postscript',
                'pdf': 'application/pdf',
                'svg': 'image/svg+xml',
                'png': 'image/png',
                'jpeg': 'image/jpeg',
                'tif': 'image/tiff',
                'emf': 'application/emf'
            }

            self.set_header('Content-Type', mimetypes.get(fmt, 'binary'))

            buff = io.BytesIO()
            managers['reference'].canvas.print_figure(buff, format=fmt)
            self.write(buff.getvalue())

    class WebSocket(tornado.websocket.WebSocketHandler):
        """
        A websocket for interactive communication between the plot in
        the browser and the server.

        In addition to the methods required by tornado, it is required to
        have two callback methods:

            - ``send_json(json_content)`` is called by matplotlib when
              it needs to send json to the browser.  `json_content` is
              a JSON tree (Python dictionary), and it is the responsibility
              of this implementation to encode it as a string to send over
              the socket.

            - ``send_binary(blob)`` is called to send binary image data
              to the browser.
        """
        supports_binary = True

        def open(self, figname):
            # Register the websocket with the FigureManager.
            self.figname = figname
            manager = self.application.managers[figname]
            manager.add_web_socket(self)
            if hasattr(self, 'set_nodelay'):
                self.set_nodelay(True)

        def on_close(self):
            # When the socket is closed, deregister the websocket with
            # the FigureManager.
            manager = self.application.managers[self.figname]
            manager.remove_web_socket(self)

        def on_message(self, message):
            # The 'supports_binary' message is relevant to the
            # websocket itself.  The other messages get passed along
            # to matplotlib as-is.

            # Every message has a "type" and a "figure_id".
            message = json.loads(message)
            if message['type'] == 'supports_binary':
                self.supports_binary = message['value']
            else:
                manager = self.application.managers[self.figname]
                manager.handle_json(message)

        def send_json(self, content):
            self.write_message(json.dumps(content))

        def send_binary(self, blob):
            if self.supports_binary:
                self.write_message(blob, binary=True)
            else:
                data_uri = "data:image/png;base64,{0}".format(
                    blob.encode('base64').replace('\n', ''))
                self.write_message(data_uri)

    def restart_wfs(self, wfs):
        """
        If there's a configuration change, provide a way to reload the specified WFS
        """
        del self.wfs_systems[wfs]
        self.wfs_systems[wfs] = wfs
        print("self.wfs_systems[wfs] = WFSFactory(wfs=wfs)")

    def __init__(self):
        self.wfs = None
        self.wfs_systems = {}
        self.wfs_names = ['newf9', 'f9', 'f5', 'mmirs']
        for w in self.wfs_names:
            self.wfs_systems[w] = w  # WFSFactory(wfs=w)
        self.figures = {}
        self.managers = {}
        if 'WFSROOT' in os.environ:
            self.datadir = os.environ['WFSROOT']
        else:
            self.datadir = "/mmt/shwfs/datadir"

        handlers = [
            (r"/", self.HomeHandler),
            (r"/select", self.SelectHandler),
            (r"/wfspage", self.WFSPageHandler),
            (r"/connect", self.ConnectHandler),
            (r"/disconnect", self.DisconnectHandler),
            (r"/analyze", self.AnalyzeHandler),
            (r"/m1correct", self.M1CorrectHandler),
            (r"/m2correct", self.M2CorrectHandler),
            (r"/recenter", self.RecenterHandler),
            (r"/restart", self.RestartHandler),
            (r"/setdatadir", self.DataDirHandler),
            (r"/m1gain", self.M1GainHandler),
            (r"/m2gain", self.M2GainHandler),
            (r'/mpl.js', self.MplJs),
            (r'/download.([a-z0-9.]+)', self.Download),
            (r'/([0-9]+)/ws', self.WebSocket)
        ]

        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            debug=True
        )
        super(WFSServ, self).__init__(handlers, **settings)


if __name__ == "__main__":
    application = WFSServ()

    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(8080)

    print("http://127.0.0.1:8080/")
    print("Press Ctrl+C to quit")

    tornado.ioloop.IOLoop.instance().start()
