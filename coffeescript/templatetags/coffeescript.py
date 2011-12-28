from ..cache import get_cache_key, get_hexdigest, get_hashed_mtime
from ..settings import COFFEESCRIPT_EXECUTABLE, COFFEESCRIPT_USE_CACHE,\
    COFFEESCRIPT_CACHE_TIMEOUT, COFFEESCRIPT_OUTPUT_DIR
from django.conf import settings
from django.core.cache import cache
from django.template.base import Library, Node
import logging
import shlex
import subprocess
import os


logger = logging.getLogger("coffeescript")
register = Library()


class InlineCoffeescriptNode(Node):

    def __init__(self, nodelist):
        self.nodelist = nodelist

    def compile(self, source):
        args = shlex.split("%s -c -s -p" % COFFEESCRIPT_EXECUTABLE)

        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out, errors = p.communicate(source.encode("utf-8"))
        if out:
            return out.decode("utf-8")
        elif errors:
            return errors.decode("utf-8")

        return u""

    def render(self, context):
        output = self.nodelist.render(context)

        if COFFEESCRIPT_USE_CACHE:
            cache_key = get_cache_key(get_hexdigest(output))
            cached = cache.get(cache_key, None)
            if cached is not None:
                return cached
            output = self.compile(output)
            cache.set(cache_key, output, COFFEESCRIPT_CACHE_TIMEOUT)
            return output
        else:
            return self.compile(output)


@register.tag(name="inlinecoffeescript")
def do_inlinecoffeescript(parser, token):
    nodelist = parser.parse(("endinlinecoffeescript",))
    parser.delete_first_token()
    return InlineCoffeescriptNode(nodelist)


@register.simple_tag
def coffeescript(path):

    try:
        STATIC_ROOT = settings.STATIC_ROOT
    except AttributeError:
        STATIC_ROOT = settings.MEDIA_ROOT

    full_path = os.path.join(STATIC_ROOT, path)
    filename = os.path.split(path)[-1]

    output_directory = os.path.join(STATIC_ROOT, COFFEESCRIPT_OUTPUT_DIR, os.path.dirname(path))

    hashed_mtime = get_hashed_mtime(full_path)

    if filename.endswith(".coffee"):
        base_filename = filename[:-7]
    else:
        base_filename = filename

    output_path = os.path.join(output_directory, "%s-%s.js" % (base_filename, hashed_mtime))

    if not os.path.exists(output_path):
        source_file = open(full_path)
        source = source_file.read()
        source_file.close()

        args = shlex.split("%s -c -s -p" % COFFEESCRIPT_EXECUTABLE)
        p = subprocess.Popen(args, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, errors = p.communicate(source)
        if out:
            if not os.path.exists(output_directory):
                os.makedirs(output_directory)
            compiled_file = open(output_path, "w+")
            compiled_file.write(out)
            compiled_file.close()

            # Remove old files
            compiled_filename = os.path.split(output_path)[-1]
            for filename in os.listdir(output_directory):
                if filename.startswith(base_filename) and filename != compiled_filename:
                    os.remove(os.path.join(output_directory, filename))
        elif errors:
            logger.error(errors)
            return path

    return output_path[len(STATIC_ROOT):].replace(os.sep, '/').lstrip("/")


@register.tag("coffeescripts")
def coffeescripts(parser, token):
    nodelist = parser.parse(("endcoffeescripts",))
    parser.delete_first_token()
    return Coffeescripts(token, nodelist)

class Coffeescripts(Node):

    def __init__(self, token, nodelist):
        self.token = token
        self.nodelist = nodelist

    def compile(self, output_path, input_paths):

        try:
            STATIC_ROOT = settings.STATIC_ROOT
        except AttributeError:
            STATIC_ROOT = settings.MEDIA_ROOT

        output_directory = os.path.join(STATIC_ROOT, COFFEESCRIPT_OUTPUT_DIR, os.path.dirname(output_path))
        full_path = os.path.join(STATIC_ROOT, output_path)
        hashed_mtime = get_hashed_mtime(full_path)
        base_filename = os.path.split(output_path)[-1]

        output_path = os.path.join(output_directory, "%s-cache.js" % base_filename)

        if os.path.exists(output_path):
          output_mtime = os.path.getmtime(output_path)
          compilation_necessary = False
          for input_path in input_paths:
            input_path += ".coffee"
            input_path = os.path.join(STATIC_ROOT, input_path)
            if os.path.getmtime(input_path) > output_mtime:
              compilation_necessary = True
              break
        else:
          compilation_necessary = True

        if compilation_necessary:
          if os.path.exists(output_path):
            os.remove(output_path)
          concatenated_source = ""
          for input_path in input_paths:
            input_path += ".coffee"
            full_path = os.path.join(STATIC_ROOT, input_path)
            filename = os.path.split(full_path)[-1]
            source_file = open(full_path)
            concatenated_source += source_file.read()+"\n"
            source_file.close()

          args = shlex.split("%s -c -s -p" % COFFEESCRIPT_EXECUTABLE)
          p = subprocess.Popen(args, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
          out, errors = p.communicate(concatenated_source)
          if out:
            if not os.path.exists(output_directory):
              os.makedirs(output_directory)
            compiled_file = open(output_path, "w+")
            compiled_file.write(out)
            compiled_file.close()
          elif errors:
            logger.error(errors)
            return output_path
        output_path = output_path[len(STATIC_ROOT):].replace(os.sep, '/').lstrip("/")
        return output_path

    def render(self, context):
        token_list = self.token.split_contents()
        output_path = token_list[1].strip('"')
        content = self.nodelist.render(context)
        input_paths = content.split("\n")
        input_paths = [path.strip() for path in input_paths]
        input_paths = filter(None, input_paths)
        output_path = self.compile(output_path, input_paths)
        return output_path
