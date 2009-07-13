import datetime
import pysolr
from django.conf import settings
from django.test import TestCase
from haystack import indexes
from haystack.sites import SearchSite
from haystack.backends.solr_backend import SearchBackend, SearchQuery
from haystack.query import SearchQuerySet
from core.models import MockModel, AnotherMockModel


class SolrMockSearchIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr='author')
    pub_date = indexes.DateField(model_attr='pub_date')


class SolrSearchBackendTestCase(TestCase):
    def setUp(self):
        super(SolrSearchBackendTestCase, self).setUp()
        
        # Stow.
        self.old_solr_url = getattr(settings, 'HAYSTACK_SOLR_URL', 'http://localhost:9001/solr/test_default')
        settings.HAYSTACK_SOLR_URL = 'http://localhost:9001/solr/test_default'
        
        self.raw_solr = pysolr.Solr(settings.HAYSTACK_SOLR_URL)
        self.raw_solr.delete(q='*:*')
        
        self.site = SearchSite()
        self.sb = SearchBackend(site=self.site)
        self.smmi = SolrMockSearchIndex(MockModel, backend=self.sb)
        self.site.register(MockModel, SolrMockSearchIndex)
        
        # Stow.
        import haystack
        self.old_site = haystack.site
        haystack.site = self.site
        
        self.sample_objs = []
        
        for i in xrange(1, 4):
            mock = MockModel()
            mock.id = i
            mock.author = 'daniel%s' % i
            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            self.sample_objs.append(mock)
    
    def tearDown(self):
        import haystack
        haystack.site = self.old_site
        settings.HAYSTACK_SOLR_URL = self.old_solr_url
        super(SolrSearchBackendTestCase, self).tearDown()
    
    def test_update(self):
        self.sb.update(self.smmi, self.sample_objs)
        
        # Check what Solr thinks is there.
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        self.assertEqual(self.raw_solr.search('*:*').docs, [{'django_id': '1', 'django_ct': 'core.mockmodel', 'name': 'daniel1', 'text': 'Indexed!\n1', 'pub_date': '2009-02-24T00:00:00Z', 'id': 'core.mockmodel.1'}, {'django_id': '2', 'django_ct': 'core.mockmodel', 'name': 'daniel2', 'text': 'Indexed!\n2', 'pub_date': '2009-02-23T00:00:00Z', 'id': 'core.mockmodel.2'}, {'django_id': '3', 'django_ct': 'core.mockmodel', 'name': 'daniel3', 'text': 'Indexed!\n3', 'pub_date': '2009-02-22T00:00:00Z', 'id': 'core.mockmodel.3'}])
    
    def test_remove(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.sb.remove(self.sample_objs[0])
        self.assertEqual(self.raw_solr.search('*:*').hits, 2)
        self.assertEqual(self.raw_solr.search('*:*').docs, [{'django_id': '2', 'django_ct': 'core.mockmodel', 'name': 'daniel2', 'text': 'Indexed!\n2', 'pub_date': '2009-02-23T00:00:00Z', 'id': 'core.mockmodel.2'}, {'django_id': '3', 'django_ct': 'core.mockmodel', 'name': 'daniel3', 'text': 'Indexed!\n3', 'pub_date': '2009-02-22T00:00:00Z', 'id': 'core.mockmodel.3'}])
    
    def test_clear(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.sb.clear()
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)
        
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.sb.clear([AnotherMockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.sb.clear([MockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)
        
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.sb.clear([AnotherMockModel, MockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)
    
    def test_search(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        self.assertEqual(self.sb.search(''), [])
        self.assertEqual(self.sb.search('*:*')['hits'], 3)
        self.assertEqual([result.pk for result in self.sb.search('*:*')['results']], ['1', '2', '3'])
        
        self.assertEqual(self.sb.search('', highlight=True), [])
        self.assertEqual(self.sb.search('Index', highlight=True)['hits'], 3)
        self.assertEqual([result.highlighted['text'][0] for result in self.sb.search('Index', highlight=True)['results']], ['<em>Indexed</em>!\n1', '<em>Indexed</em>!\n2', '<em>Indexed</em>!\n3'])
        
        self.assertEqual(self.sb.search('Indx')['hits'], 0)
        self.assertEqual(self.sb.search('Indx')['spelling_suggestion'], 'index')
        
        self.assertEqual(self.sb.search('', facets=['name']), [])
        results = self.sb.search('Index', facets=['name'])
        self.assertEqual(results['hits'], 3)
        self.assertEqual(results['facets']['fields']['name'], [('daniel1', 1), ('daniel2', 1), ('daniel3', 1)])
        
        self.assertEqual(self.sb.search('', date_facets={'pub_date': {'start_date': datetime.date(2008, 2, 26), 'end_date': datetime.date(2008, 2, 26), 'gap': '/MONTH'}}), [])
        results = self.sb.search('Index', date_facets={'pub_date': {'start_date': datetime.date(2008, 2, 26), 'end_date': datetime.date(2008, 2, 26), 'gap': '/MONTH'}})
        self.assertEqual(results['hits'], 3)
        # DRL_TODO: Correct output but no counts. Another case of needing better test data?
        self.assertEqual(results['facets']['dates']['pub_date'], {'end': '2008-02-26T00:00:00Z', 'gap': '/MONTH'})
        
        self.assertEqual(self.sb.search('', query_facets={'name': '[* TO e]'}), [])
        results = self.sb.search('Index', query_facets={'name': '[* TO e]'})
        self.assertEqual(results['hits'], 3)
        self.assertEqual(results['facets']['queries'], {'name:[* TO e]': 3})
        
        self.assertEqual(self.sb.search('', narrow_queries=['name:daniel1']), [])
        results = self.sb.search('Index', narrow_queries=['name:daniel1'])
        self.assertEqual(results['hits'], 1)
    
    def test_more_like_this(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        
        # DRL_TODO: Even though I've confirmed MLT works correctly, it doesn't
        #           seem to find any similar documents. Need better sample data?
        self.assertEqual(self.sb.more_like_this(self.sample_objs[0])['hits'], 0)
        self.assertEqual([result.pk for result in self.sb.more_like_this(self.sample_objs[0])['results']], [])


class LiveSolrSearchQueryTestCase(TestCase):
    def setUp(self):
        super(LiveSolrSearchQueryTestCase, self).setUp()
        
        # Stow.
        self.old_solr_url = getattr(settings, 'HAYSTACK_SOLR_URL', 'http://localhost:9001/solr/test_default')
        settings.HAYSTACK_SOLR_URL = 'http://localhost:9001/solr/test_default'
        
        self.sq = SearchQuery(backend=SearchBackend())
    
    def tearDown(self):
        settings.HAYSTACK_SOLR_URL = self.old_solr_url
        super(LiveSolrSearchQueryTestCase, self).tearDown()
    
    def test_get_spelling(self):
        self.sq.add_filter('content', 'Indx')
        self.assertEqual(self.sq.get_spelling_suggestion(), u'index')


class LiveSolrSearchQuerySetTestCase(TestCase):
    """Used to test actual implementation details of the SearchQuerySet."""
    def setUp(self):
        super(LiveSolrSearchQuerySetTestCase, self).setUp()
        self.sqs = SearchQuerySet()
        
        # With the models registered, you get the proper bits.
        import haystack
        from haystack.sites import SearchSite
        
        # Stow.
        self.old_site = haystack.site
        test_site = SearchSite()
        test_site.register(MockModel)
        haystack.site = test_site
    
    def tearDown(self):
        # Restore.
        import haystack
        haystack.site = self.old_site
        super(LiveSolrSearchQuerySetTestCase, self).tearDown()
    
    def test_load_all(self):
        sqs = self.sqs.load_all()
        self.assert_(isinstance(sqs, SearchQuerySet))
        self.assertEqual(sqs[0].object.foo, 'bar')
    
    def test_load_all_queryset(self):
        sqs = self.sqs.load_all()
        self.assertEqual(len(sqs._load_all_querysets), 0)
        
        sqs = sqs.load_all_queryset(MockModel, MockModel.objects.filter(id__gt=1))
        self.assert_(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs._load_all_querysets), 1)
        self.assertEqual([obj.object.id for obj in sqs], [2, 3])
