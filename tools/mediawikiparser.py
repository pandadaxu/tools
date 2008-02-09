#!/usr/bin/python

# Process Wikipedia dump files
#
# Jeremy Mortis (mortis@ucalgary.ca)

import os
import sys
import re
from simplexmlparser import SimpleXMLParser

from aarddict.article import Article
from aarddict.article import Tag
import aarddict.pyuca

import wikimarkup

class MediaWikiParser(SimpleXMLParser):

    def __init__(self, collator, metadata, consumer):
        SimpleXMLParser.__init__(self)
        self.collator = collator
        self.metadata = metadata
        self.consumer = consumer
        self.tagstack = []
        self.title = ""
        self.text = ""
        self.StartElementHandler = self.handleStartElement
        self.EndElementHandler = self.handleEndElement
        self.CharacterDataHandler = self.handleCharacterData

        self.reRedirect = re.compile(r"^#REDIRECT", re.IGNORECASE)
        self.reSquare2 = re.compile(r"\[\[(.*?)\]\]")
        self.reLeadingSpaces = re.compile(r"^\s*", re.MULTILINE)
        self.reTrailingSpaces = re.compile(r"\s*$", re.MULTILINE)


    def handleStartElement(self, tag, attrs):
        self.tagstack.append([tag, []])


    def handleEndElement(self, tag):

        if not self.tagstack:
            return
        
        entry = self.tagstack.pop()
        
        if entry[0] != tag:
            sys.stderr.write("Mismatched mediawiki tag: %s in %s at %s\n" % (repr(tag), repr(self.title), repr(entry)))
            return

        entrytext = "".join(entry[1])

        if tag == "sitename":
            self.metadata["title"] = self.clean(entrytext, oneline=True)

        elif tag == "base":
            m = re.compile(r"http://(.*?)\.wikipedia").match(entrytext)
            if m:
                self.metadata["index_language"] = m.group(1)
                self.metadata["article_language"] = m.group(1)
        
        elif tag == "title":
            self.title = self.clean(entrytext, oneline=True)
        
        elif tag == "text":
            self.text = entrytext
                        
        elif tag == "page":
            
            if self.weakRedirect(self.title, self.text):
                return
            try:
                self.text = self.translateWikiMarkupToHTML(self.text).strip()
            except Exception, e:
                sys.stderr.write("Unable to translate wiki markup: %s\n" % str(e))
                self.text = ""
            self.consumer(self.title, self.text)
            return
            
    def handleCharacterData(self, data):

        if not self.tagstack:
            if data.strip():
                sys.stderr.write("orphan data: '%s'\n" % data)
            return
        self.tagstack[-1][1].append(data)


    def clean(self, s, oneline = False):
        if oneline:
            s = s.replace("\n", " ")
        s = self.reLeadingSpaces.sub("", s)
        s = self.reTrailingSpaces.sub("", s)
        return s.strip()
    
    def weakRedirect(self, title, text):
        if self.reRedirect.search(text): 
            m = self.reSquare2.search(text)
            if m:
                redirect = m.group(1)
                redirectKey = self.collator.getCollationKey(redirect)
                titleKey = self.collator.getCollationKey(title)
                if redirectKey == titleKey:
                    #sys.stderr.write("Weak redirect: " + repr(title) + " " + repr(redirect) + "\n")
                    return True
        return False

    def translateWikiMarkupToHTML(self, text):
        text = self.reRedirect.sub("See:", text)
        text = wikimarkup.parse(text, False)
        text = parseLinks(text)
        return text

def parseLinks(s):
    
    while 1:
        left = s.find("[[")
        if left < 0:
            break
        nest = 2
        right = left + 2
        while (nest > 0) and (right < len(s)):
            if s[right] == "[":
                nest = nest + 1
            elif s[right] == "]":
                nest = nest - 1
            right = right + 1
                        
        if (nest != 0):
            #sys.stderr.write("Mismatched brackets: %s %s %s\n" % (str(left), str(right), str(nest)))
            return ""
                        
        link = s[left:right]
            
        # recursively parse nested links
        link = parseLinks(link[2:-2])
        if not link:
            return ""

        p = link.split("|")

        c = p[0].find(":")

        if c >= 0:
            t = p[0][:c]
            if t == "Image":
                r = '<img href="' + p[0][c+1:] + '">' + p[-1] + '</img>'
            else:
                r = ""
        else:
            r = '<a href="' + p[0] + '">' + p[-1] + '</a>'
            

        s = "".join([s[:left] + r + s[right:]]) 
        
    return s

template_re = re.compile(r'\{\{([^\|]+)\|?(.*)\}\}')

def parseTemplate(s):
    m = template_re.search(s)
    if m:
        name = m.group(1)
        params = {}
        param_str = m.group(2)
        param_pairs=param_str.split("|");
        paramcount = 0
        for pair in param_pairs:
            key, sep, val = pair.partition("=")
            if key:
                if val:
                    params[key] = val
                else:
                    paramcount += 1
                    params[paramcount] = key
        return name, params
