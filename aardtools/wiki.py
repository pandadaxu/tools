# This file is part of Aard Dictionary Tools <http://aarddict.org>.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License <http://www.gnu.org/licenses/gpl-3.0.txt>
# for more details.
#
# Copyright (C) 2008-2009  Igor Tkach

import functools
import re
import logging
import os
import sys

import simplejson

from mwlib import uparser, xhtmlwriter
from mwlib.log import Log
Log.logfile = None

import mwaardwriter

tojson = functools.partial(simplejson.dumps, ensure_ascii=False)

import multiprocessing
from multiprocessing import Pool, TimeoutError
from mwlib.cdbwiki import WikiDB, normname
from mwlib._version import version as mwlib_version
from mwlib.siteinfo import get_siteinfo

import gc

wikidb = None
log = logging.getLogger()

def _create_wikidb(cdbdir, lang):
    global wikidb
    wikidb = Wiki(cdbdir, lang)

def _init_process(cdbdir, lang):
    global log
    log = multiprocessing.get_logger()
    _create_wikidb(cdbdir, lang)

def convert(title):
    gc.collect()
    try:
        text = wikidb.getRawArticle(title, resolveRedirect=False)

        if not text:
            raise RuntimeError('Article "%r" is empty' % title)

        mo = wikidb.redirect_rex.search(text)
        if mo:
            redirect = mo.group('redirect')
            redirect = normname(redirect.split("|", 1)[0].split("#", 1)[0])
            meta = {u'r': redirect}
            return title, tojson(('', [], meta))

        mwobject = uparser.parseString(title=title,
                                       raw=text,
                                       wikidb=wikidb,
                                       lang=wikidb.lang)
        xhtmlwriter.preprocess(mwobject)
        text, tags = mwaardwriter.convert(mwobject)
    except Exception:
        msg = 'Failed to process article %r' % title
        log.exception(msg)
        raise RuntimeError(msg)
    else:            
        return title, tojson((text.rstrip(), tags))

class Wiki(WikiDB):

    def __init__(self, cdbdir, lang):
        WikiDB.__init__(self, cdbdir)
        self.lang = lang
        self.siteinfo = get_siteinfo(self.lang)

    def get_siteinfo(self):
        return self.siteinfo

default_lic_fname = 'fdl-1.2.txt'
default_copyright_fname = 'copyright.txt'
default_metadata_fname = 'metadata.ini'

class WikiParser():

    def __init__(self, options, consumer):
        self.consumer = consumer

        wiki_lang = options.wiki_lang
        metadata_dir = os.path.join(sys.prefix,'share/aardtools/wiki/%s' % wiki_lang)
        default_metadata_dir = os.path.join(sys.prefix,'share/aardtools/wiki/%s' % 'en')

        try:
            siteinfo = get_siteinfo(wiki_lang)
            sitename = siteinfo['general']['sitename']
            sitelang = siteinfo['general']['lang']
        except:
            log.fatal('Failed to read siteinfo for language %(lang)s, '
                      'can''t proceed. '
                      'Check that siteinfo-%(lang)s.json exists in mwlib.siteinfo, '
                      'run fetch_siteinfo.py %(lang)s if not', dict(lang=wiki_lang))
            raise SystemExit(1)

        
        metadata_files = []
        if options.metadata:
            metadata_files.append(options.metadata)
        else:
            metadata_files.append(os.path.join(default_metadata_dir, default_metadata_fname))
            metadata_files.append(os.path.join(metadata_dir, default_metadata_fname))
                                
        from ConfigParser import ConfigParser
        c = ConfigParser(defaults={'ver': options.dict_ver, 
                                   'lang': wiki_lang,
                                   'update': options.dict_update,
                                   'name': sitename,
                                   'sitelang': sitelang})
        read_metadata_files = c.read(metadata_files)
        if not read_metadata_files:
            log.warn('No metadata files read.')
        else:
            log.info('Using metadata from %s', ', '.join(read_metadata_files))
        for opt in c.options('metadata'):
            value = c.get('metadata', opt)
            self.consumer.add_metadata(opt, value)

        if not options.license and 'license' not in self.consumer.metadata:
            license_file = os.path.join(metadata_dir, default_lic_fname)
            log.info('Looking for license text in %s', license_file)
            if not os.path.exists(license_file):
                log.info('File %s doesn\'t exist', license_file)
                license_file = os.path.join(default_metadata_dir, default_lic_fname)
                log.info('Looking for license text in %s', license_file)
                try:
                    with open(license_file) as f:
                        license_text = f.read()
                        self.consumer.add_metadata('license', license_text)
                        log.info('Using license text from %s', license_file)
                except IOError, e:
                    log.warn('No license text will be written to the '
                             'output dictionary: %s', str(e))

        if not options.copyright and 'copyright' not in self.consumer.metadata:
            copyright_file = os.path.join(metadata_dir, default_copyright_fname)
            log.info('Looking for copyright notice text in %s', copyright_file)
            if not os.path.exists(copyright_file):
                log.info('File %s doesn\'t exist', copyright_file)
                copyright_file = os.path.join(default_metadata_dir, default_copyright_fname)
                log.info('Looking for copyright notice text in %s', copyright_file)
                try:
                    with open(copyright_file) as f:
                        copyright_text = f.read()
                        self.consumer.add_metadata('copyright', copyright_text)
                        log.info('Using copyright notice text from %s', copyright_file)
                except IOError, e:
                    log.warn('No copyright notice text will be written to the '
                             'output dictionary: %s', str(e))

        self.lang = None
        self._set_lang(wiki_lang)

        self.consumer.add_metadata('mwlib',
                                   '.'.join(str(v) for v in mwlib_version))
        self.special_article_re = re.compile(r'^\w+:\S', re.UNICODE)
        self.processes = options.processes if options.processes else None
        self.pool = None
        self.active_processes = multiprocessing.active_children()
        self.timeout = options.timeout
        self.timedout_count = 0
        self.error_count = 0
        self.start = options.start
        self.end = options.end
        if options.nomp:
            log.info('Disabling multiprocessing')
            self.parse = self.parse_simple
        else:
            self.parse = self.parse_mp

    def _set_lang(self, lang):
        self.lang = lang
        self.consumer.add_metadata("index_language", lang)
        self.consumer.add_metadata("article_language", lang)
        log.info('Language: %s', self.lang)

    def articles(self, f):
        if self.start > 0:
            log.info('Skipping to article %d', self.start)
        _create_wikidb(f, self.lang)
        skipped_count = 0

        for read_count, title in enumerate(wikidb.articles()):
            
            if read_count <= self.start:
                continue

            if self.end and read_count > self.end:
                log.info('Reached article %d, stopping.', self.end)
                break

            if self.special_article_re.match(title):
                skipped_count += 1
                log.debug('Special article %s, skipping (%d so far)',
                              title.encode('utf8'), skipped_count)
                continue

            log.debug('Yielding "%s" for processing', title.encode('utf8'))

            yield title
            gc.collect()


    def reset_pool(self, cdbdir):
        if self.pool:
            log.info('Terminating current worker pool')
            self.pool.terminate()
        log.info('Creating new worker pool with wiki cdb at %s', cdbdir)

        self.pool = Pool(processes=self.processes,
                         initializer=_init_process,
                         initargs=[cdbdir, self.lang])

    def log_runtime_error(self):
        self.error_count += 1
        log.warn('Failed to process article (%d so far)', self.error_count)

    def parse_simple(self, f):
        self.consumer.add_metadata('article_format', 'json')
        articles = self.articles(f)
        article_count = 0
        for a in articles:
            try:
                result = convert(a)
                title, serialized = result
                self.consumer.add_article(title, serialized)
                article_count += 1
            except RuntimeError:
                self.log_runtime_error()

        self.consumer.add_metadata("article_count", article_count)

    def parse_mp(self, f):
        try:
            self.consumer.add_metadata('article_format', 'json')
            articles = self.articles(f)
            self.reset_pool(f)
            resulti = self.pool.imap_unordered(convert, articles)
            article_count = 0
            while True:
                try:
                    result = resulti.next(self.timeout)
                    title, serialized = result
                    self.consumer.add_article(title, serialized)
                    article_count += 1
                except StopIteration:
                    break
                except TimeoutError:
                    self.timedout_count += 1
                    log.error('Worker pool timed out (%d time(s) so far)',
                                  self.timedout_count)
                    self.reset_pool(f)
                    resulti = self.pool.imap_unordered(convert, articles)
                except AssertionError:
                    self.log_runtime_error()
                except RuntimeError:
                    self.log_runtime_error()
                except KeyboardInterrupt:
                    log.error('Keyboard interrupt: '
                                  'terminating worker pool')
                    self.pool.terminate()
                    raise

            self.consumer.add_metadata("article_count", article_count)
        finally:
            self.pool.close()
            self.pool.join()
