import threading
import sys
sys.path.append('..')

import database.query as query
import util.logger as logger
import yiasa.spider as spider
from yiasa.spider import Spider

class Handler:
    def __init__(self, log, db, settings):
        self.log = log
        self.db = db
        self.settings = settings
        self.threadId = 0

    def start_threads(self):
        started = 0
        while len(self.settings.spiderThreadList) < self.settings.get_threads() and len(self.settings.queue) > 0:
            domain = self.settings.queue.pop()
            self.setup_db_row(domain)

            s = Spider(self.log, self.db, self.threadId, domain)
            t = threading.Thread(target=s.start_crawl, name=self.threadId)
            t.daemon = True
            self.settings.spiderThreadList.append(t)
            t.start()
            self.threadId += 1
            self.log.log(logger.LogLevel.INFO, 'Started new spider: %s' % s.to_string())
    
    def setup_db_row(self, domain):
        domainExists = self.db.query_exists(query.QUERY_GET_CRAWLED_DOMAIN(), (domain, ))
        if domainExists is False:
            self.db.query_commit(query.QUERY_INSERT_TABLE_CRAWLED(), (domain, 0, 0, 0, 'NULL',))
            input()