from zine._core import _create_zine
import os.path
from libopencore import auth
from opencore_zinefarm.opencoreglue import CustomRequestApp
from opencore_zinefarm.opencoreglue import find_role_for_user
from opencore_zinefarm.opencoreglue import new_instance
from webob import Request, Response
import webob.exc 

class IndexPage(Exception):
    pass

class ZineFarm(object):
    def __init__(self, zine_instances_directory,
                 shared_secret_filename,
                 admin_info_filename,
                 internal_root_url,
                 public_root_url):
        self.zine_instances_directory = zine_instances_directory
        self.shared_secret_filename = shared_secret_filename
        self.admin_info_filename = admin_info_filename
        self.internal_root_url = internal_root_url
        self.public_root_url = public_root_url

    def get_instance_folder(self, environ):
        project = environ.get('HTTP_X_OPENPLANS_PROJECT')

        blog = Request(environ).path_info_peek()
        if not blog:
            raise IndexPage

        instance_folder = os.path.join(
            self.zine_instances_directory, project, blog)
        return instance_folder

    def __call__(self, environ, start_response):
        # figure out which Zine instance to dispatch to
        # based on special request header
        project = environ.get('HTTP_X_OPENPLANS_PROJECT')
        if not project: 
            return webob.exc.HTTPNotFound("No blog found for project %s" % project)(environ, start_response)

        # we use a copy of the environ because it's rude to modify 
        # the environ in place; something upstream of us might not
        # be expecting this injection
        environ_copy = environ.copy()

        # pass the shared_secret_filename through in the environment
        # so that the request object can find it when it needs to
        # authenticate the requesting user from a cookie
        environ_copy['OPENCORE_SECRET_FILENAME'] = self.shared_secret_filename

        # likewise pass the admin_info_filename through so that
        # zine can use site admin credentials to query projects'
        # security policies and memberhips (in case it's a closed
        # project)
        environ_copy['OPENCORE_ADMIN_INFO_FILENAME'] = self.admin_info_filename

        # and we pass the internal_root_url in the environ as well.
        # this is used to construct the url used when querying the
        # projects for their security policies and memberships
        environ_copy['OPENCORE_INTERNAL_ROOT_URL']  = self.internal_root_url

        #environ_copy['SCRIPT_NAME'] = environ_copy['HTTP_X_FORWARDED_PATH']

        req = Request(environ_copy)
        print req.path_info_peek()
        if not req.path_info_peek():
            return self.index_page(req)(environ, start_response)

        if req.path_info.endswith("create"):
            return self.make_instance(environ_copy, start_response)

        req.path_info_pop()

        # zine makes it very difficult to instantiate its wsgi app for some reason
        # you have to much around with another module's global
        # i'm not sure if this is safe, and it's certainly not kosher
        app = object.__new__(CustomRequestApp)
        from zine import _core
        _core._application = app

        instance_folder = self.get_instance_folder(environ)
        app.__init__(instance_folder)

        resp = req.get_response(app)
        if resp.status_int == 403:
            if req.remote_user is None:
                resp = webob.exc.HTTPFound()
                resp.location = '/'.join((
                        self.public_root_url.rstrip("/"),
                        "login")) + \
                        "?came_from=" + \
                        req.path

        return resp(environ_copy, start_response)

    def index_page(self, req):
        project = req.environ.get('HTTP_X_OPENPLANS_PROJECT')
        index_folder = os.path.join(
            self.zine_instances_directory, project)
        if not os.path.exists(index_folder):
            os.makedirs(index_folder)
        blogs = os.listdir(index_folder)
        return Response(" ".join(blogs))

    def make_instance(self, environ, start_response):
        req = Request(environ)
        try:
            user = auth.get_user(req, self.shared_secret_filename)
        except:
            return webob.exc.HTTPForbidden("not logged in")(
                environ, start_response)
        role = find_role_for_user(user, 
                                  environ['HTTP_X_OPENPLANS_PROJECT'],
                                  environ)
        if role != "ProjectAdmin":
            return webob.exc.HTTPForbidden("can't do that now")(
                environ, start_response)

        blog_url = "%s://%s%s/%s" % (
            environ['HTTP_X_FORWARDED_SCHEME'],
            environ['HTTP_X_FORWARDED_SERVER'],
            environ['HTTP_X_FORWARDED_PATH'],
            Request(environ).path_info_peek())
        print blog_url

        blog_url = '/'.join((Request(environ).application_url, 
                             Request(environ).path_info_peek()))
        # blog_url must end in a trailing slash for url generation to work properly,
        # otherwise zine.utils.http:make_external_url will swallow it when building urls to posts;
        #  make_external_url("http://coactivate.org/foo", "bar/baz") -> "http://coactivate.org/bar/baz")
        #  make_external_url("http://coactivate.org/foo/", "bar/baz") -> "http://coactivate.org/foo/bar/baz")
        blog_url = blog_url.rstrip("/") + '/'

        instance = self.get_instance_folder(environ)
        dburi = "sqlite:///%s/database.db" % instance
        if not os.path.exists(instance):
            os.makedirs(instance)
        new_instance(dburi,
                     instance,
                     blog_url)
        return webob.exc.HTTPFound(location=blog_url)(
            environ, start_response)

def app_factory(global_conf,
                zine_instances_directory=None, 
                shared_secret_filename=None,
                admin_info_filename=None,
                internal_root_url=None,
                public_root_url=None,
                **kw):
    assert zine_instances_directory is not None, \
        "zine_instances_directory must be supplied"
    assert os.path.isdir(zine_instances_directory), \
        "zine_instances_directory `%s` does not exist" % zine_instances_directory
    assert shared_secret_filename is not None and os.path.isfile(shared_secret_filename), \
        "shared_secret_filename must be supplied and must be an existing file"
    assert admin_info_filename is not None and os.path.isfile(admin_info_filename), \
        "admin_info_filename must be supplied and must be an existing file"
    assert internal_root_url is not None, \
        "internal_root_url must be supplied"
    assert public_root_url is not None, \
        "public_root_url must be supplied"
    
    return ZineFarm(zine_instances_directory, 
                    shared_secret_filename,
                    admin_info_filename,
                    internal_root_url, 
                    public_root_url)
