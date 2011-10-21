"""
spec -- generate test description from test class/method names
---------------------------------------------------------------

spec lets you generate a "specification" similar to testdox_ . The spec plugin
can generate simple documentation directly from class and method names of test
cases. For example, a test case like::

  class TestFoobar:
      def test_can_be_automatically_documented(self):
          pass
      def test_is_a_singleton(self):
          pass

during the test run will generate the following specification::

  Foobar
  - can be automatically documented
  - is a singleton

Test functions put directly into a module will have a context based
on the name of the containing module. For example, if you define
functions test_are_marked_as_deprecated() and
test_doesnt_work_with_sets() in a module test_containers.py,
you'll get the following specs::

  Containers
  - are marked as deprecated
  - doesn't work with sets

You can also override specification names generated by spec plugin by adding
a docstring to the appropriate class, module or function.

Test generators are also supported. Context of a generator is the generator
name and yielded values are specifications. For example, generator
test_product_of_even_numbers_is_even() yielding three different tests
will generate the following specification::

  Product of even numbers is even
  - holds for 2, 8
  - holds for 4, 10
  - holds for 12, 6

:Note: docstrings support is experimental. Enable by --spec-doctests.

Specifications are generated for those doctest examples which generate an
output, raise an exception or have a comment. Thus, this doctest::

  >>> 2 + 3
  5
  >>> None
  >>> None # is nothing
  >>> foobar
  Traceback (most recent call last):
    ...
  NameError: name 'foobar' is not defined

will generate::

  - 2 + 3 returns 5
  - None is nothing
  - foobar throws "NameError: name 'foobar' is not defined"

Use cases
~~~~~~~~~

If you follow a good naming convention for your tests you'll get free
up-to-date specification of your application - it will be as accurate
as your tests are.

Options
~~~~~~~

``--with-spec`` enables the plugin, and automatically sets the verbose
level for nose to "detailed output".  During the test run all your
test descriptions will be shown as a special kind of specification -
your test classes set up a context and test methods set up a single
specification.

``--spec-color`` enables colored output. Successful tests will be marked
as green, while failed/error cases as red. Skipped and deprecated test
cases will be shown in yellow. You need an ANSI terminal to use this.

``--spec--doctests`` enables experimental support for doctests.

.. _testdox: http://agiledox.sourceforge.net/
"""

import doctest
import inspect
import os
import re
import types
import unittest
from StringIO import StringIO

try:
    from unittest.runner import _WritelnDecorator  # Python 2.7
except ImportError:
    from unittest import _WritelnDecorator

import nose
from nose.plugins import Plugin


################################################################################
## Functions for constructing specifications based on nose testing objects.
################################################################################

def dispatch_on_type(dispatch_table, instance):
    for type, func in dispatch_table:
        if type is True or isinstance(instance, type):
            return func(instance)


def remove_leading(needle, haystack):
    """Remove leading needle string (if exists).

    >>> remove_leading('Test', 'TestThisAndThat')
    'ThisAndThat'
    >>> remove_leading('Test', 'ArbitraryName')
    'ArbitraryName'
    """
    if haystack[:len(needle)] == needle:
        return haystack[len(needle):]
    return haystack


def remove_trailing(needle, haystack):
    """Remove trailing needle string (if exists).

    >>> remove_trailing('Test', 'ThisAndThatTest')
    'ThisAndThat'
    >>> remove_trailing('Test', 'ArbitraryName')
    'ArbitraryName'
    """
    if haystack[-len(needle):] == needle:
        return haystack[:-len(needle)]
    return haystack


def remove_leading_and_trailing(needle, haystack):
    return remove_leading(needle, remove_trailing(needle, haystack))


def camel2word(string):
    """Covert name from CamelCase to "Normal case".

    >>> camel2word('CamelCase')
    'Camel case'
    >>> camel2word('CaseWithSpec')
    'Case with spec'
    """
    def wordize(match):
        return ' ' + match.group(1).lower()

    return string[0] + re.sub(r'([A-Z])', wordize, string[1:])


def complete_english(string):
    """
    >>> complete_english('dont do this')
    "don't do this"
    >>> complete_english('doesnt is matched as well')
    "doesn't is matched as well"
    """
    for x, y in [("dont", "don't"),
                ("doesnt", "doesn't"),
                ("wont", "won't"),
                ("wasnt", "wasn't")]:
        string = string.replace(x, y)
    return string


def underscore2word(string):
    return string.replace('_', ' ')


def argumentsof(test):
    if test.arg:
        if len(test.arg) == 1:
            return " for %s" % test.arg[0]
        else:
            return " for %s" % (test.arg,)
    return ""


def underscored2spec(name):
    return complete_english(underscore2word(remove_trailing('_test', remove_leading('test_', name))))


def camelcase2spec(name):
    return camel2word(remove_leading_and_trailing('Test', name))


def camelcaseDescription(object):
    return inspect.getdoc(object) or camelcase2spec(object.__name__)


def underscoredDescription(object):
    return inspect.getdoc(object) or underscored2spec(object.__name__).capitalize()


def doctestContextDescription(doctest):
    return doctest._dt_test.name


def noseMethodDescription(test):
    return inspect.getdoc(test.method) or underscored2spec(test.method.__name__)


def unittestMethodDescription(test):
    return test._testMethodDoc or underscored2spec(test._testMethodName)


def noseFunctionDescription(test):
    # Special case for test generators.
    if test.descriptor is not None:
        if hasattr(test.test, 'description'):
            return test.test.description
        return "holds for %s" % ', '.join(map(str, test.arg))
    return test.test.func_doc or underscored2spec(test.test.func_name)


# Different than other similar functions, this one returns a generator
# of specifications.
def doctestExamplesDescription(test):
    for ex in test._dt_test.examples:
        source = ex.source.replace("\n", " ")
        want = None
        if '#' in source:
            source, want = source.rsplit('#', 1)
        elif ex.exc_msg:
            want = "throws \"%s\"" % ex.exc_msg.rstrip()
        elif ex.want:
            want = "returns %s" % ex.want.replace("\n", " ")

        if want:
            yield "%s %s" % (source.strip(), want.strip())


def testDescription(test):
    supported_test_types = [
        (nose.case.MethodTestCase, noseMethodDescription),
        (nose.case.FunctionTestCase, noseFunctionDescription),
        (doctest.DocTestCase, doctestExamplesDescription),
        (unittest.TestCase, unittestMethodDescription),
    ]
    return dispatch_on_type(supported_test_types, test.test)


def contextDescription(context):
    supported_context_types = [
        (types.ModuleType, underscoredDescription),
        (types.FunctionType, underscoredDescription),
        (doctest.DocTestCase, doctestContextDescription),
        # Handle both old and new style classes.
        (types.ClassType, camelcaseDescription),
        (type, camelcaseDescription),
    ]
    return dispatch_on_type(supported_context_types, context)


def testContext(test):
    # Test generators set their own contexts.
    if isinstance(test.test, nose.case.FunctionTestCase) \
           and test.test.descriptor is not None:
        return test.test.descriptor
    # So do doctests.
    elif isinstance(test.test, doctest.DocTestCase):
        return test.test
    else:
        return test.context


################################################################################
## Output stream that can be easily enabled and disabled.
################################################################################

class OutputStream(_WritelnDecorator):
    def __init__(self, on_stream, off_stream):
        self.capture_stream = StringIO()
        self.on_stream = on_stream
        self.off_stream = off_stream
        self.stream = on_stream

    def on(self):
        self.stream = self.on_stream

    def off(self):
        self.stream = self.off_stream

    def capture(self):
        self.capture_stream.truncate()
        self.stream = self.capture_stream

    def get_captured(self):
        self.capture_stream.seek(0)
        return self.capture_stream.read()


class SpecOutputStream(OutputStream):
    def print_text(self, text):
        self.on()
        self.write(text)
        self.off()

    def print_line(self, line=''):
        self.print_text(line + "\n")

    def print_context(self, context):
        self.print_line("\n%s" % contextDescription(context))

    def print_spec(self, colorized, test, status=None):
        spec = testDescription(test)
        if isinstance(spec, types.GeneratorType):
            for s in spec:
                self._print_spec(colorized, s, status)
        elif spec:
            self._print_spec(colorized, spec, status)

    def _print_spec(self, colorized, spec, status=None):
        if status:
            self.print_line(colorized("- %s (%s)" % (spec, status)))
        else:
            self.print_line(colorized("- %s" % spec))

################################################################################
## Color helpers.
################################################################################

color_end = "\x1b[1;0m"
colors = dict(green="\x1b[1;32m", red="\x1b[1;31m", yellow="\x1b[1;33m")


def in_color(color, text):
    """Colorize text, adding color to each line so that the color shows up
    correctly with the less -R as well as more and normal shell.
    """
    return "".join("%s%s%s" % (colors[color], line, color_end)
                                       for line in text.splitlines(True))


################################################################################
## Plugin itself.
################################################################################

class Spec(Plugin):
    """Generate specification from test class/method names.
    """
    score = 1100  # must be higher than Deprecated and Skip plugins scores

    def options(self, parser, env=os.environ):
        Plugin.options(self, parser, env)
        parser.add_option('--spec-color', action='store_true',
                          dest='spec_color',
                          default=env.get('NOSE_SPEC_COLOR'),
                          help="Show coloured (red/green) output for specifications "
                          "[NOSE_SPEC_COLOR]")
        parser.add_option('--spec-doctests', action='store_true',
                          dest='spec_doctests',
                          default=env.get('NOSE_SPEC_DOCTESTS'),
                          help="Include doctests in specifications "
                          "[NOSE_SPEC_DOCTESTS]")

    def configure(self, options, config):
        Plugin.configure(self, options, config)

        if options.enable_plugin_spec:
            options.verbosity = max(options.verbosity, 2)

        if options.spec_color:
            self._colorize = lambda color: lambda text: in_color(color, text)
        else:
            self._colorize = lambda color: lambda text: text

        self.spec_doctests = options.spec_doctests

    def begin(self):
        self.current_context = None

    def setOutputStream(self, stream):
        self.stream = SpecOutputStream(stream, open(os.devnull, 'w'))
        return self.stream

    def beforeTest(self, test):
        context = testContext(test)
        if context != self.current_context:
            self._print_context(context)
            self.current_context = context

        self.stream.off()

    def addSuccess(self, test):
        self._print_spec('green', test)

    def addFailure(self, test, err):
        self._print_spec('red', test, 'FAILED')

    def addError(self, test, err):
        def print_spec_func(color, message):
            return lambda _: self._print_spec(color, test, message)

        supported_error_types = [
            (nose.DeprecatedTest, print_spec_func('yellow', 'DEPRECATED')),
            (nose.SkipTest, print_spec_func('yellow', 'SKIPPED')),
            (True, print_spec_func('red',    'ERROR')),
        ]

        dispatch_on_type(supported_error_types, err[1])

    def afterTest(self, test):
        self.stream.capture()

    def finalize(self, result):
        self.stream.on()
        # Print test run summary.
        self.stream.writeln(self.stream.get_captured())

    def _print_context(self, context):
        if isinstance(context, doctest.DocTestCase) and not self.spec_doctests:
            return
        self.stream.print_context(context)

    def _print_spec(self, color, test, status=None):
        if isinstance(test.test, doctest.DocTestCase) and not self.spec_doctests:
            return
        self.stream.print_spec(self._colorize(color), test, status)


if __name__ == '__main__':
    doctest.testmod()
