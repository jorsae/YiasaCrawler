from bs4 import BeautifulSoup
import requests
import re, time
import sys
from datetime import datetime
sys.path.append('..')

import util.logger as logger
import database.query as query
import yiasa.handler

class Spider:
    queue = set()
    re_url = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    @staticmethod
    def print_queue():
        print(len(Spider.queue))
        print(Spider.queue)

    def __init__(self, log, db, name, domain):
        self.log = log
        self.db = db
        self.name = name
        # Removes '/' suffix if it's there
        self.domain = domain[:len(domain)-1] if domain[len(domain) - 1] == '/' else domain
        self.queue = set()
        self.completed_queue = set()
        self.new_domains = set()
        self.crawled_urls = 0
        self.robots = {"disallow":[], "allow":[]}
        self.crawl_delay = 0
        self.max_urls = 100 # Max amount of urls to be crawled

    def to_string(self):
        return 'Name:%s @domain: %s' % (self.name, self.domain)
    
    def start_crawl(self):
        """ Getting ready to crawl a domain.
            This means, parsing robots.txt and crawling top-url for new urls """
        self.parse_robots()

        req = self.request(self.domain)
        soup = BeautifulSoup(req.text, 'html.parser')
        valid_urls = self.extract_url(soup)
        self.add_to_queue(valid_urls)
        print(valid_urls) # TODO: For debugging only
        self.crawl()
    
    def request(self, url):
        """ sends a http request to url """
        self.crawled_urls += 1
        return requests.get(url)

    def crawl(self):
        """ Iterate through the entire queue stack """
        while self.queue and self.crawled_urls < self.max_urls:
            if(self.crawled_urls % 10 == 0):
                self.log.log(logger.LogLevel.INFO, 'Thread:%s | New: %d | %d/%d' % (self.name, len(self.new_domains), self.crawled_urls, self.max_urls))
            url = self.queue.pop()
            self.completed_queue.add(url)
            req = self.request(url)
            crawlHistory = self.db.query_commit(query.QUERY_INSERT_TABLE_CRAWL_HISTORY(), (self.domain, url, req.status_code, url, datetime.now()))
            if crawlHistory is False:
                self.log.log(logger.LogLevel.WARNING, 'Unable to insert into crawl_history: %s' % url)

            soup = BeautifulSoup(req.text, 'html.parser')
            valid_urls = self.extract_url(soup)
            self.add_to_queue(valid_urls)
            #self.log.log(logger.LogLevel.DEBUG, 'CrawlId: %s, Crawled: %d, queue: %d, completed_queue: %d, new_domains: %d' % (self.name, self.crawled_urls, len(self.queue), len(self.completed_queue), len(self.new_domains)))
            time.sleep(self.crawl_delay)
        
        # Finished crawling, insert stats to DB
        self.finish_crawl()
        
    def finish_crawl(self):
        """ Finished crawling, inserts result to DB """
        domainExists = self.db.query_exists(query.QUERY_GET_CRAWLED_DOMAIN(), (self.domain, ))
        if domainExists:
            dbCrawled = self.db.query_commit(query.QUERY_UPDATE_TABLE_CRAWLED(), (len(self.new_domains), self.crawled_urls, 1, datetime.now(), self.domain))
            if dbCrawled:
                self.log.log(logger.LogLevel.INFO, 'Added crawl stats to DB from: %s' % self.name)
            else:
                self.log.log(logger.LogLevel.WARNING, 'Unable to insert crawl stats to DB from: %s' % self.name)
        else:
            self.log.log(logger.LogLevel.CRITICAL, 'Domain: %s was finshed crawling, but does not exist in DB!' % self.domain)

    
    def add_to_queue(self, urls):
        """ Adds a list of urls to the queue """
        for url in urls:
            if self.domain not in url:
                self.new_domains.add(url)
            elif url not in self.queue and url not in self.completed_queue:
                if self.url_follow_robots(url):
                    self.queue.add(url)

    def extract_url(self, soup):
        """ Extract all urls from a soup """
        valid_urls = set()
        urls = [link.get('href') for link in soup.find_all('a', href=True)]
        for url in urls:
            if self.valid_url(url):
                valid_urls.add(url)
                continue
            if url.startswith('mailto'):
                continue
            if url == '':
                continue
            url = url[1:len(url)] if url[0] == '.' else url # Remove '.' prefix in url, if websites use it
            url = url if url[0] == '/' else '/%s' % url # Adds '/' to url, if it's a relative path url
            url = '%s%s' % (self.domain, url)
            if self.valid_url(url):
                valid_urls.add(url)
        return valid_urls

    def url_follow_robots(self, url):
        """ Checks if a url breaks the robots.txt rules """
        for disallow in self.robots["disallow"]:
            invalid = re.search(disallow, url, re.IGNORECASE)
            if invalid:
                return False
        return True

    def parse_robots(self):
        """ Parses robots.txt. disallow/allow is placed in self.robots """
        r = requests.get('%s/robots.txt' % self.domain)
        if r.status_code == 404:
            print('No robots.txt')
            return
            
        user_agent = True
        for line in r.text.lower().split('\n'):
            if line.startswith('user-agent'):
                if '*' in line:
                    user_agent = True
                else:
                    user_agent = False
            if user_agent:
                if line.startswith('disallow:'):
                    disallow = line.split(':')[1].replace(' ', '')
                    disallow = disallow.replace('*', '.+')
                    self.robots["disallow"].append(disallow)
                elif line.startswith('allow:'):
                    self.robots["allow"].append(line.split(':')[1].replace(' ', ''))
                elif line.startswith('crawl-delay'):
                    delay = int(re.search('\d+', line).group())
                    self.crawl_delay = delay

    def valid_url(self, url):
        """ Checks if a url is valid """
        return re.match(Spider.re_url, url) is not None