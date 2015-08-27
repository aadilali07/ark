
""" Loads, processes, and stores the site's configuration data. """

import os
import importlib
import time
import re
import sys
import hashlib
import pickle

from . import utils
from . import renderers


# Stores the path to the site's home directory.
_homedir = None

# Stores the path to the site's output directory.
_outdir = None

# Stores the path to the site's theme directory.
_themedir = None

# Stores the site's configuration data.
_config = None

# Stores rendered include strings loaded from the inc directory.
_includes = None

# Stores the build's start time.
_starttime = None

# Stores a count of the number of pages rendered.
_prendered = None

# Stores a count of the number of pages written.
_pwritten = None

# Stores cached page hashes from the last build run.
_oldhashes = None

# Stores new page hashes from the current build run.
_newhashes = None

# Stores build flags appended to the 'build' command.
_buildflags = None


def init(options):
    """ Initialize the site model before building. """

    # Store the start time.
    global _starttime
    _starttime = time.time()

    # Initialize the page count variables.
    global _prendered, _pwritten
    _prendered = _pwritten = 0

    global _buildflags
    _buildflags = options['flags']

    # Store the site's home directory.
    global _homedir
    _homedir = options['home']

    # Load the site's configuration data.
    global _config
    _config = _load_site_config()

    # Determine the theme directory.
    global _themedir
    _themedir = _set_theme_dir(options)

    # Determine the output directory.
    global _outdir
    _outdir = options.get('out') or home('out')

    # Determine the urls of the root directory index pages.
    for typeid in _config['types']:
        _config['types'][typeid]['index_url'] = index_url(typeid)

    # Load any extensions we can find.
    _load_extensions()

    # Load the cached page hashes from the last build, if they exist.
    global _oldhashes, _newhashes
    _oldhashes, _newhashes = _load_hashes(), {}

    # Clear the output directory.
    if options.get('clear'):
        utils.cleardir(out())


def exit():
    """ Runs at the end of the build process before exiting. """
    _save_hashes()


def home(*append):
    """ Returns the path to the home directory. """
    return os.path.join(_homedir, *append)


def src(*append):
    """ Returns the path to the home/src directory. """
    return home('src', *append)


def out(*append):
    """ Returns the path to the home/out directory. """
    return os.path.join(_outdir, *append)


def theme(*append):
    """ Returns the path to the theme directory. """
    return os.path.join(_themedir, *append)


def flags():
    """ Returns the list of build flags. """
    return _buildflags


def includes():
    """ Returns a dictionary of processed strings from the inc directory. """
    global _includes
    if _includes is None:
        _includes = {}
        if os.path.isdir(home('inc')):
            for finfo in utils.srcfiles(home('inc')):
                text, _ = utils.load(finfo.path)
                _includes[finfo.base] = renderers.render(text, finfo.ext)
    return _includes


def config(key=None, fallback=None):
    """ Returns the dictionary of site configuration data. """
    if key:
        return _config.get(key, fallback)
    else:
        return _config


def slugs(typeid, *append):
    """ Returns the output slug list for the specified record type. """
    typeslug = _config['types'][typeid]['slug']
    sluglist = [slug for slug in typeslug.split('/') if slug]
    sluglist.extend(append)
    return sluglist


def url(slugs):
    """ Returns the URL corresponding to the specified slug list. """
    return '@root/' + '/'.join(slugs) + '//'


def paged_url(slugs, page_number, total_pages):
    """ Returns the paged URL corresponding to the specified slug list. """
    if page_number == 1:
        return url(slugs + ['index'])
    elif 2 <= page_number <= total_pages:
        return url(slugs + ['page-%s' % page_number])
    else:
        return ''


def index_url(typeid):
    """ Returns the URL of the index page of the specified record type. """
    if _config['types'][typeid]['indexed']:
        if _config['types'][typeid]['homepage']:
            return url(['index'])
        else:
            return url(slugs(typeid, 'index'))
    else:
        return ''


def build_time():
    """ Returns the build time in seconds. """
    return time.time() - _starttime


def page_count():
    """ Returns the count of pages rendered and written. """
    return _prendered, _pwritten


def increment_pages_rendered():
    """ Increments the count of pages rendered. """
    global _prendered
    _prendered += 1


def increment_pages_written():
    """ Increments the count of pages written. """
    global _pwritten
    _pwritten += 1


def type_from_src(srcpath):
    """ Determines the record type from the source path. """
    slugs = os.path.relpath(srcpath, src()).replace('\\', '/').split('/')
    for slug in slugs:
        if slug.startswith('['):
            return slug.strip('[]')


def slugs_from_src(srcdir, *append):
    """ Returns the output slug list for the specified source directory. """
    typeid = type_from_src(srcdir)
    dirnames = os.path.relpath(srcdir, src()).replace('\\', '/').split('/')
    sluglist = slugs(typeid)
    sluglist.extend(utils.slugify(d) for d in dirnames if not d.startswith('['))
    sluglist.extend(append)
    return sluglist


def trail_from_src(srcdir):
    """ Returns the name trail for the specified source directory. """
    typeid = type_from_src(srcdir)
    dirnames = os.path.relpath(srcdir, src()).replace('\\', '/').split('/')
    trail = [_config['types'][typeid]['name']]
    trail.extend(name for name in dirnames if not name.startswith('['))
    return trail


def _load_site_config():
    """ Loads and normalizes the site's configuration data. """

    data, configstr = {}, ''

    # Look for a config.py file in the home directory.
    if os.path.isfile(home('config.py')):
        configstr = open(home('config.py'), encoding='utf-8').read()

    # Evaluate the file contents as a string of Python code.
    if configstr:
        exec(configstr, data)
        del data['__builtins__']

    # Set a default extension for generated files.
    # The extension can be an empty string, an arbitrary file extension,
    # or a forward slash for directory-style urls.
    data.setdefault('extension', '.html')

    # If a root has been supplied, make sure it ends with a trailing slash.
    # The root string can be a full url (http://example.com/), a single
    # slash (/), or an empty string (the default) for page relative urls.
    if data.setdefault('root', '') and not data['root'].endswith('/'):
        data['root'] += '/'

    # The 'types' dictionary stores configuration data for record types.
    data.setdefault('types', {})

    # Assemble a list of the site's record types from its [type] directories.
    types = [
        dirinfo.name.strip('[]')
            for dirinfo in utils.subdirs(src())
                if dirinfo.name.startswith('[')
    ]

    # Supply default values for any missing type data.
    for typeid in types:
        settings = {
            'name': utils.titlecase(typeid),
            'slug': utils.slugify(typeid),
            'tag_slug': 'tags',
            'indexed': True,
            'order_by': 'date',
            'reverse': True,
            'per_index': 10,
            'per_tag_index': 10,
            'homepage': False,
        }
        if typeid == 'pages':
            settings['slug'] = ''
            settings['indexed'] = False
        settings.update(data['types'].get(typeid, {}))
        data['types'][typeid] = settings
        data['types'][typeid]['id'] = typeid

    # Strip any type entries that don't refer to actual [type] directories.
    for typeid in list(data['types']):
        if not typeid in types:
            del data['types'][typeid]

    return data


def _load_extensions():
    """ Load any Python modules found in the extensions directories. """
    dirpaths = [os.path.join(os.path.dirname(__file__), 'ext')]
    if os.path.isdir(home('ext')):
        dirpaths.append(home('ext'))
    for dirpath in dirpaths:
        sys.path.insert(0, dirpath)
        names = [
            os.path.splitext(name)[0]
                for name in os.listdir(dirpath)
                    if not name[0] in '_.'
        ]
        for name in names:
            extension = importlib.import_module(name)
        sys.path.pop(0)


def _set_theme_dir(options):
    """ Determines the theme directory to use for the build. """
    theme = options.get('theme') or config('theme') or 'vanilla'

    # Have we been given a directory name in the site's theme library.
    if os.path.isdir(home('lib', theme)):
        return home('lib', theme)

    # Have we been given a directory name in the global theme library.
    if os.getenv('ARK_THEMES'):
        if os.path.isdir(os.path.join(os.getenv('ARK_THEMES'), theme)):
            return os.path.join(os.getenv('ARK_THEMES'), theme)

    # Have we been given a directory path?
    if os.path.isdir(theme):
        return theme

    # Last chance. Do we have a bundled theme we can use?
    if os.path.isdir(os.path.join(os.path.dirname(__file__), 'init', 'lib', theme)):
        return os.path.join(os.path.dirname(__file__), 'init', 'lib', theme)

    sys.exit("Error: cannot locate theme directory '%s'." % theme)


def hashmatch(filepath, content):
    """ Returns true if there is an existing file at `filepath` whose hash
    matches that of the string `content`. """
    _newhashes[filepath] = hashlib.sha1(content.encode()).hexdigest()
    if os.path.exists(filepath):
        return _oldhashes.get(filepath) == _newhashes[filepath]
    else:
        return False


def _load_hashes():
    """ Loads cached page hashes from the last build run. """
    if os.path.exists(home('.ark', 'hashes.pickle')):
        with open(home('.ark', 'hashes.pickle'), 'rb') as file:
            return pickle.load(file)
    else:
        return {}


def _save_hashes():
    """ Caches page hashes to disk for the next build run. """
    if not os.path.exists(home('.ark')):
        os.makedirs(home('.ark'))
    with open(home('.ark', 'hashes.pickle'), 'wb') as file:
        pickle.dump(_newhashes, file)
