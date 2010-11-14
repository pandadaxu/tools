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

import os
import json
import re
import mmap

from collections import defaultdict

#original expression from
#http://stackoverflow.com/questions/694344/regular-expression-that-matches-between-quotes-containing-escaped-quotes
#"(?:[^\\"]+|\\.)*"
#some examples don't have closing quote which
#make the subn with this expression hang
#quoted_text = re.compile(r'"(?:[^\\"]+|\\.)*["|\n]')

#make it a capturing group so that we can get rid of quotes
quoted_text = re.compile(r'"([^"]+|\.)*["|\n]')

ref = re.compile(r"`(\w+)'")

wordnet = None

def total(inputfile, options):
    global wordnet
    wordnet = WordNet(inputfile)
    wordnet.prepare()
    count = 0
    for title in wordnet.collector:
        has_article = False
        for piece in wordnet.collector[title]:
            if isinstance(piece, tuple):
                count += 1
            else:
                has_article = True
        if has_article:
            count += 1
    return count


def collect_articles(input_file, options, compiler):
    wordnet.process(compiler)

def make_input(input_file_name):
    return input_file_name #this should be wordnet dir, leave it alone

def iterlines(wordnetdir):
    dict_dir = os.path.join(wordnetdir, 'dict')
    for name in os.listdir(dict_dir):
        if name.startswith('data.'):
            with open(os.path.join(dict_dir, name)) as f:
                for line in f:
                    if not line.startswith('  '):
                        yield line

class SynSet(object):

    def __init__(self, line):
        self.line = line
        meta, self.gloss = line.split('|')
        self.meta_parts = meta.split()

    @property
    def offset(self):
        return int(self.meta_parts[0])

    @property
    def lex_filenum(self):
        return self.meta_parts[1]

    @property
    def ss_type(self):
        return self.meta_parts[2]

    @property
    def w_cnt(self):
        return int(self.meta_parts[3], 16)

    @property
    def words(self):
        return [self.meta_parts[4+2*i].replace('_', ' ')
                for i in range(self.w_cnt)]

    @property
    def pointers(self):
        p_cnt_index = 4+2*self.w_cnt
        p_cnt = self.meta_parts[p_cnt_index]
        pointer_count = int(p_cnt)
        start = p_cnt_index + 1
        return [Pointer(*self.meta_parts[start+i*4:start+(i+1)*4])
                for i in range(pointer_count)]

    def __repr__(self):
        return 'SynSet(%r)' % self.line


class Pointer(object):

    n = {'!':    'Antonym',
         '@':    'Hypernym',
         '@i':   'Instance Hypernym',
         '':     'Hyponym',
         'i':    'Instance Hyponym',
         '#m':   'Member holonym',
         '#s':   'Substance holonym',
         '#p':   'Part holonym',
         '%m':   'Member meronym',
         '%s':   'Substance meronym',
         '%p':   'Part meronym',
         '=':    'Attribute',
         '+':    'Derivationally related form',
         ';c':   'Domain of synset - TOPIC',
         '-c':   'Member of this domain - TOPIC',
         ';r':   'Domain of synset - REGION',
         '-r':   'Member of this domain - REGION',
         ';u':   'Domain of synset - USAGE',
         '-u':   'Member of this domain - USAGE'}

    v = {'!':   'Antonym',
         '@':    'Hypernym',
         '':    'Hyponym',
         '*':   'Entailment',
         '>':   'Cause',
         '^':   'Also see',
         '$':   'Verb Group',
         '+':   'Derivationally related form',
         ';c':  'Domain of synset - TOPIC',
         ';r':  'Domain of synset - REGION',
         ';u':  'Domain of synset - USAGE'}

    a = s = {'!':    'Antonym',
             '&':    'Similar to',
             '<':    'Participle of verb',
             '\\':    'Pertainym (pertains to noun)',
             '=':    'Attribute',
             '^':    'Also see',
             ';c':    'Domain of synset - TOPIC',
             ';r':    'Domain of synset - REGION',
             ';u':    'Domain of synset - USAGE'}

    r = {'!':    'Antonym',
         '\\':   'Derived from adjective',
         '+':   'Derivationally related form',
         ';c':   'Domain of synset - TOPIC',
         ';r':   'Domain of synset - REGION',
         ';u':   'Domain of synset - USAGE',
         }


    def __init__(self, symbol, offset, pos, source_target):
        self.symbol = symbol
        self.offset = int(offset)
        self.pos = pos
        self.source_target = source_target
        self.source = int(source_target[:2], 16)
        self.target = int(source_target[2:], 16)

    @property
    def symbol_desc(self):
        try:
            return getattr(self, self.pos)[self.symbol]
        except KeyError:
            print 'WARNING: unknown pointer symbol %s for %s ' % (self.symbol, self.pos)
            return None
        

    def __repr__(self):
        return ('Pointer(%r, %r, %r, %r)' %
                (self.symbol, self.offset, 
                 self.pos, self.source_target))


class WordNet():

    def __init__(self, wordnetdir):
        self.wordnetdir = wordnetdir
        self.collector = defaultdict(list)

    def prepare(self):
        ss_types = {'n': 'noun',
                    'v': 'verb',
                    'a': 'adjective',
                    's': 'adjective satellite',
                    'r': 'adverb'}
        mmap_files = {}
        file2pos = {'data.adj': ['a', 's'],
                    'data.adv': ['r'],
                    'data.noun': ['n'],
                    'data.verb': ['v']}
        dict_dir = os.path.join(self.wordnetdir, 'dict')
        for name in os.listdir(dict_dir):
            if name.startswith('data.'):
                if name in file2pos:
                    f = open(os.path.join(dict_dir, name), 'r+')
                    m = mmap.mmap(f.fileno(), 0)
                    for key in file2pos[name]:
                        mmap_files[key] = m
        seen_redirects = set()

        for line in iterlines(self.wordnetdir):
            synset = SynSet(line)
            # print synset
            words = synset.words
            orig_title = title = words[0]

            gloss_with_examples, _ = quoted_text.subn(lambda x: '<span class="ex">%s</span>' %
                                                   x.group(1), synset.gloss)

            gloss_with_examples, _ = ref.subn(lambda x: '<a href="%s">%s</a>' % 
                                              (x.group(1), x.group(1)), gloss_with_examples)

            synonyms = []
            for title in words[1:]:
                synonyms.append('<a href="%s">%s</a>' % (title, title))
                if (title, orig_title) not in seen_redirects:
                    seen_redirects.add((title, orig_title))
                    self.collector[title].append(('', [], {'r': orig_title}))

            synonyms_str = ('<br/><b>Synonyms:</b> %s' %
                            ', '.join(synonyms) if synonyms else '')

            pointers = []
            for pointer in synset.pointers:
                symbol_desc = pointer.symbol_desc
                if not symbol_desc:
                    continue
                mmap_file = mmap_files[pointer.pos]
                mmap_file.seek(pointer.offset)
                referenced_synset = SynSet(mmap_file.readline())
                # print '%r ==> %r' % (pointer, referenced_synset)
                s = '<b>%s:</b> ' % pointer.symbol_desc

                # print 'word count: ', len(words), 'source: ', pointer.source
                # print 'target word count: ', len(referenced_synset.words), 'target: ', pointer.target

                s += '%s - %s' % (words[pointer.source - 1], 
                                  referenced_synset.words[pointer.target - 1])
                pointers.append(s)
            pointers_str = '<br/>'.join(pointers)

            self.collector[orig_title].append('<span class="pos">%s</span> %s%s<br/>%s' %
                                              (ss_types[synset.ss_type],
                                               gloss_with_examples,
                                               synonyms_str,
                                               pointers_str))



    def process(self, consumer):

        readme_file = os.path.join(self.wordnetdir, 'README')
        license_file = os.path.join(self.wordnetdir, 'LICENSE')

        consumer.add_metadata('title', 'WordNet')
        consumer.add_metadata('version', '3.0')
        consumer.add_metadata('index_language', 'en')
        consumer.add_metadata('article_language', 'en')

        with open(readme_file) as f:
            consumer.add_metadata('description', '<pre>%s</pre>' % f.read())

        with open(license_file) as f:
            consumer.add_metadata('license', f.read())

        article_template = '<h1>%s</h1><span>%s</span>'

        for title in self.collector:
            pieces = self.collector[title]
            article_pieces = []
            redirects = []
            for piece in pieces:
                if isinstance(piece, tuple):
                    redirects.append(piece)
                else:
                    article_pieces.append(piece)

            article_pieces_count = len(article_pieces)

            text = None
            if article_pieces_count > 1:
                ol = ['<ol>'] + ['<li>%s</li>' % ap for ap in article_pieces] + ['</ol>']
                text = (article_template % (title, ''.join(ol)))
            elif article_pieces_count == 1:
                text = (article_template %
                        (title, article_pieces[0]))

            if text:
                consumer.add_article(title,
                                     json.dumps((text, [])),
                                     redirect=False)

            #add redirects after articles so that
            #redirects to titles that have both articles and
            #redirects land on articles
            for redirect in redirects:
                consumer.add_article(title,
                                     json.dumps(redirect),
                                     redirect=True)