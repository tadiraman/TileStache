""" The configuration bits of TileStache.

TileStache configuration is stored in JSON files, and is composed of two main
top-level sections: "cache" and "layers". There are examples of both in this
minimal sample configuration:

    {
      "cache": {"name": "Test"},
      "layers": {
        "example": {
            "provider": {"name": "mapnik", "mapfile": "examples/style.xml"},,
            "projection": "spherical mercator"
        } 
      }
    }

The contents of the "cache" section are described in greater detail in the
TileStache.Caches module documentation. Here is a different sample:

    "cache": {
      "name": "Disk",
      "path": "/tmp/stache",
      "umask": "0000"
    }

The "layers" section is a dictionary of layer names which are specified in the
URL of an individual tile. More detail on the configuration of individual layers
can be found in the TileStache.Core module documentation. Another sample:

    {
      "cache": ...,
      "layers": 
      {
        "example-name":
        {
            "provider": { ... },
            "metatile": { ... },
            "preview": { ... },
            "stale lock timeout": ...,
            "projection": ...
        }
      }
    }

In-depth explanations of the layer components can be found in the module
documentation for TileStache.Providers, TileStache.Core, and TileStache.Geography.
"""

from sys import stderr, modules
from os.path import realpath, join as pathjoin
from urlparse import urljoin, urlparse
from json import dumps

try:
    from json import dumps as json_dumps
except ImportError:
    from simplejson import dumps as json_dumps

from ModestMaps.Geo import Location
from ModestMaps.Core import Coordinate

import Core
import Caches
import Providers
import Geography

class Configuration:
    """ A complete site configuration, with a collection of Layer objects.
    
        Attributes:
        
          cache:
            Cache instance, e.g. TileStache.Caches.Disk etc.
            See TileStache.Caches for details on what makes
            a usable cache.
        
          layers:
            Dictionary of layers keyed by name.
            
            When creating a custom layers dictionary, e.g. for dynamic
            layer collections backed by some external configuration,
            these dictionary methods must be provided for a complete
            collection of layers:
            
              keys():
                Return list of layer name strings.

              items():
                Return list of (name, layer) pairs.

              __contains__(key):
                Return boolean true if given key is an existing layer.
                
              __getitem__(key):
                Return existing layer object for given key or raise KeyError.
        
          dirpath:
            Local filesystem path for this configuration,
            useful for expanding relative paths.
    """
    def __init__(self, cache, dirpath):
        self.cache = cache
        self.dirpath = dirpath
        self.layers = {}

class Bounds:
    """ Coordinate bounding box for tiles.
    """
    def __init__(self, upper_left_high, lower_right_low):
        """ Two required Coordinate objects defining tile pyramid bounds.
        
            Boundaries are inclusive: upper_left_high is the left-most column,
            upper-most row, and highest zoom level; lower_right_low is the
            right-most column, furthest-dwn row, and lowest zoom level.
        """
        self.upper_left_high = upper_left_high
        self.lower_right_low = lower_right_low
    
    def excludes(self, tile):
        """ Check a tile Coordinate against the bounds, return true/false.
        """
        if tile.zoom > self.upper_left_high.zoom:
            # too zoomed-in
            return True
        
        if tile.zoom < self.lower_right_low.zoom:
            # too zoomed-out
            return True

        # check the top-left tile corner against the lower-right bound
        _tile = tile.zoomTo(self.lower_right_low.zoom)
        
        if _tile.column > self.lower_right_low.column:
            # too far right
            return True
        
        if _tile.row > self.lower_right_low.row:
            # too far down
            return True

        # check the bottom-right tile corner against the upper-left bound
        __tile = tile.right().down().zoomTo(self.upper_left_high.zoom)
        
        if __tile.column < self.upper_left_high.column:
            # too far left
            return True
        
        if __tile.row < self.upper_left_high.row:
            # too far up
            return True
        
        return False
    
    def __str__(self):
        return 'Bound %s - %s' % (self.upper_left_high, self.lower_right_low)

def buildConfiguration(config_dict, dirpath='.'):
    """ Build a configuration dictionary into a Configuration object.
    
        The second argument is an optional dirpath that specifies where in the
        local filesystem the parsed dictionary originated, to make it possible
        to resolve relative paths.
    """
    cache_dict = config_dict.get('cache', {})
    cache = _parseConfigfileCache(cache_dict, dirpath)
    
    config = Configuration(cache, dirpath)
    
    for (name, layer_dict) in config_dict.get('layers', {}).items():
        config.layers[name] = _parseConfigfileLayer(layer_dict, config, dirpath)

    return config

def enforcedLocalPath(relpath, dirpath, context='Path'):
    """ Return a forced local path, relative to a directory.
    
        Throw an error if the combination of path and directory seems to
        specify a remote path, e.g. "/path" and "http://example.com".
    
        Although a configuration file can be parsed from a remote URL, some
        paths (e.g. the location of a disk cache) must be local to the server.
        In cases where we mix a remote configuration location with a local
        cache location, e.g. "http://example.com/tilestache.cfg", the disk path
        must include the "file://" prefix instead of an ambiguous absolute
        path such as "/tmp/tilestache".
    """
    parsed_dir = urlparse(dirpath)
    parsed_rel = urlparse(relpath)
    
    if parsed_rel.scheme not in ('file', ''):
        raise Core.KnownUnknown('%s path must be a local file path, absolute or "file://", not "%s".' % (context, relpath))
    
    if parsed_dir.scheme not in ('file', '') and parsed_rel.scheme != 'file':
        raise Core.KnownUnknown('%s path must start with "file://" in a remote configuration ("%s" relative to %s)' % (context, relpath, dirpath))
    
    if parsed_rel.scheme == 'file':
        # file:// is an absolute local reference for the disk cache.
        return parsed_rel.path

    if parsed_dir.scheme == 'file':
        # file:// is an absolute local reference for the directory.
        return urljoin(parsed_dir.path, parsed_rel.path)
    
    # nothing has a scheme, it's probably just a bunch of
    # dumb local paths, so let's see what happens next.
    return pathjoin(dirpath, relpath)

def _parseConfigfileCache(cache_dict, dirpath):
    """ Used by parseConfigfile() to parse just the cache parts of a config.
    """
    if 'name' in cache_dict:
        _class = Caches.getCacheByName(cache_dict['name'])
        kwargs = {}
        
        def add_kwargs(*keys):
            """ Populate named keys in kwargs from cache_dict.
            """
            for key in keys:
                if key in cache_dict:
                    kwargs[key] = cache_dict[key]
        
        if _class is Caches.Test:
            if cache_dict.get('verbose', False):
                kwargs['logfunc'] = lambda msg: stderr.write(msg + '\n')
    
        elif _class is Caches.Disk:
            kwargs['path'] = enforcedLocalPath(cache_dict['path'], dirpath, 'Disk cache path')
            
            if 'umask' in cache_dict:
                kwargs['umask'] = int(cache_dict['umask'], 8)
            
            add_kwargs('dirs', 'gzip')
        
        elif _class is Caches.Multi:
            kwargs['tiers'] = [_parseConfigfileCache(tier_dict, dirpath)
                               for tier_dict in cache_dict['tiers']]
    
        elif _class is Caches.Memcache.Cache:
            add_kwargs('servers', 'lifespan', 'revision')
    
        elif _class is Caches.S3.Cache:
            add_kwargs('bucket', 'access', 'secret')
    
        else:
            raise Exception('Unknown cache: %s' % cache_dict['name'])
        
    elif 'class' in cache_dict:
        _class = loadClassPath(cache_dict['class'])
        kwargs = cache_dict.get('kwargs', {})
        kwargs = dict( [(str(k), v) for (k, v) in kwargs.items()] )

    else:
        raise Exception('Missing required cache name or class: %s' % json_dumps(cache_dict))

    cache = _class(**kwargs)

    return cache

def _parseLayerBounds(bounds_dict, projection):
    """
    """
    north, west = bounds_dict.get('north', None), bounds_dict.get('west', None)
    south, east = bounds_dict.get('south', None), bounds_dict.get('east', None)
    high, low = bounds_dict.get('high', None), bounds_dict.get('low', None)
    
    try:
        ul_hi = projection.locationCoordinate(Location(north, west)).zoomTo(high)
        lr_lo = projection.locationCoordinate(Location(south, east)).zoomTo(low)
    except TypeError:
        raise Core.KnownUnknown('Missing part of bounds for layer, need north, south, east, west, high, and low: ' + dumps(bounds_dict))
    
    return Bounds(ul_hi, lr_lo)

def _parseConfigfileLayer(layer_dict, config, dirpath):
    """ Used by parseConfigfile() to parse just the layer parts of a config.
    """
    projection = layer_dict.get('projection', 'spherical mercator')
    projection = Geography.getProjectionByName(projection)
    
    #
    # Add cache lock timeouts and preview arguments
    #
    
    layer_kwargs = {}
    
    if 'cache lifespan' in layer_dict:
        layer_kwargs['cache_lifespan'] = int(layer_dict['cache lifespan'])
    
    if 'stale lock timeout' in layer_dict:
        layer_kwargs['stale_lock_timeout'] = int(layer_dict['stale lock timeout'])
    
    if 'write cache' in layer_dict:
        layer_kwargs['write_cache'] = bool(layer_dict['write cache'])
    
    if 'allowed origin' in layer_dict:
        layer_kwargs['allowed_origin'] = str(layer_dict['allowed origin'])
    
    if 'preview' in layer_dict:
        preview_dict = layer_dict['preview']
        
        for (key, func) in zip(('lat', 'lon', 'zoom', 'ext'), (float, float, int, str)):
            if key in preview_dict:
                layer_kwargs['preview_' + key] = func(preview_dict[key])
    
    #
    # Do the bounds
    #
    
    if 'bounds' in layer_dict:
        if type(layer_dict['bounds']) is not dict:
            raise Core.KnownUnknown('Layer bounds must be a dictionary, not: ' + dumps(layer_dict['bounds']))
    
        layer_kwargs['bounds'] = _parseLayerBounds(layer_dict['bounds'], projection)
    
    #
    # Do the metatile
    #

    meta_dict = layer_dict.get('metatile', {})
    metatile_kwargs = {}

    for k in ('buffer', 'rows', 'columns'):
        if k in meta_dict:
            metatile_kwargs[k] = int(meta_dict[k])
    
    metatile = Core.Metatile(**metatile_kwargs)
    
    #
    # Do the per-format options
    #
    
    jpeg_kwargs = {}
    png_kwargs = {}

    if 'jpeg options' in layer_dict:
        jpeg_kwargs = dict([(str(k), v) for (k, v) in layer_dict['jpeg options'].items()])

    if 'png options' in layer_dict:
        png_kwargs = dict([(str(k), v) for (k, v) in layer_dict['png options'].items()])

    #
    # Do the provider
    #

    provider_dict = layer_dict['provider']

    if 'name' in provider_dict:
        _class = Providers.getProviderByName(provider_dict['name'])
        provider_kwargs = {}
        
        if _class is Providers.Mapnik:
            provider_kwargs['mapfile'] = provider_dict['mapfile']
            provider_kwargs['fonts'] = provider_dict.get('fonts', None)
        
        elif _class is Providers.Proxy:
            if 'url' in provider_dict:
                provider_kwargs['url'] = provider_dict['url']
            if 'provider' in provider_dict:
                provider_kwargs['provider_name'] = provider_dict['provider']
        
        elif _class is Providers.UrlTemplate:
            provider_kwargs['template'] = provider_dict['template']
        
        elif _class is Providers.Vector.Provider:
            provider_kwargs['driver'] = provider_dict['driver']
            provider_kwargs['parameters'] = provider_dict['parameters']
            provider_kwargs['properties'] = provider_dict.get('properties', None)
            provider_kwargs['projected'] = bool(provider_dict.get('projected', False))
            provider_kwargs['verbose'] = bool(provider_dict.get('verbose', False))
            
            if 'spacing' in provider_dict:
                provider_kwargs['spacing'] = float(provider_dict.get('spacing', 0.0))
            else:
                provider_kwargs['spacing'] = None
            
            if provider_dict.get('clipped', None) == 'padded':
                provider_kwargs['clipped'] = 'padded'
            else:
                provider_kwargs['clipped'] = bool(provider_dict.get('clipped', True))
        
        elif _class is Providers.MBTiles.Provider:
            provider_kwargs['tileset'] = provider_dict['tileset']
            
    elif 'class' in provider_dict:
        _class = loadClassPath(provider_dict['class'])
        provider_kwargs = provider_dict.get('kwargs', {})
        provider_kwargs = dict( [(str(k), v) for (k, v) in provider_kwargs.items()] )

    else:
        raise Exception('Missing required provider name or class: %s' % json_dumps(provider_dict))
    
    #
    # Finish him!
    #

    layer = Core.Layer(config, projection, metatile, **layer_kwargs)
    layer.provider = _class(layer, **provider_kwargs)
    layer.setSaveOptionsJPEG(**jpeg_kwargs)
    layer.setSaveOptionsPNG(**png_kwargs)
    
    return layer

def loadClassPath(classpath):
    """ Load external class based on a path.
        
        Example classpath: "Module.Submodule:Classname".
    
        Equivalent soon-to-be-deprecated classpath: "Module.Submodule.Classname".
    """
    if ':' in classpath:
        #
        # Just-added support for "foo:blah"-style classpaths.
        #
        modname, objname = classpath.split(':', 1)

        try:
            __import__(modname)
            module = modules[modname]
            _class = eval(objname, module.__dict__)
            
            if _class is None:
                raise Exception('eval(%(objname)s) in %(modname)s came up None' % locals())

        except Exception, e:
            raise Core.KnownUnknown('Tried to import %s, but: %s' % (classpath, e))
    
    else:
        #
        # Support for "foo.blah"-style classpaths, TODO: deprecate this in v2.
        #
        classpath = classpath.split('.')
    
        try:
            module = __import__('.'.join(classpath[:-1]), fromlist=str(classpath[-1]))
        except ImportError, e:
            raise Core.KnownUnknown('Tried to import %s, but: %s' % ('.'.join(classpath), e))
    
        try:
            _class = getattr(module, classpath[-1])
        except AttributeError, e:
            raise Core.KnownUnknown('Tried to import %s, but: %s' % ('.'.join(classpath), e))

    return _class
