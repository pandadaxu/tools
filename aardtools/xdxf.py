import logging
import functools 

from lxml import etree
import simplejson

tojson = functools.partial(simplejson.dumps, ensure_ascii=False)

class XDXFParser():
    
    def __init__(self, consumer):
        self.consumer = consumer

    def _text(self, element, tags, offset=0):
        txt = ''
        start = offset
        if element.text: 
            txt += element.text
        for c in element:            
            txt += self._text(c, tags, offset + len(txt)) 
        end = start + len(txt)
        tags.append([element.tag, start, end, dict(element.attrib)])
        if element.tail:
            txt += element.tail
        return txt
        
    def parse(self, f):
        self.consumer.add_metadata('article_format', 'json')
        for event, element in etree.iterparse(f):
            if element.tag == 'description':
                self.consumer.add_metadata(element.tag, element.text)
                element.clear()
                
            if element.tag == 'full_name':
                self.consumer.add_metadata('title', element.text)
                element.clear()
    
            if element.tag == 'xdxf':    
                self.consumer.add_metadata('article_language', 
                                           element.get('lang_to'))
                self.consumer.add_metadata('index_language', 
                                           element.get('lang_from'))
                self.consumer.add_metadata('xdxf_format', 
                                           element.get('format'))
                element.clear()
    
            if element.tag == 'ar':
                tags = []
                txt = self._text(element, tags)
                for i, title_elements in enumerate(element.findall('k')):
                    first_title = None
                    try:
                        title = title_elements.text
                        if i == 0:
                            first_title = title
                            serialized = tojson((txt, tags, {}))
                        else:
                            logging.debug('Redirect %s ==> %s', 
                                          title.encode('utf8'), 
                                          first_title.encode('utf8'))
                            meta = {u'redirect': first_title}
                            serialized = tojson(('', [], meta))
                        self.consumer.add_article(title, serialized)
                    except:
                        logging.exception('Skipping bad article')
                element.clear()                        
