from django.db.models import signals
import haystack
from haystack.fields import *


class DeclarativeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        attrs['fields'] = {}
        
        # Inherit any fields from parent(s).
        try:
            parents = [b for b in bases if issubclass(b, SearchIndex)]
            
            for p in parents:
                fields = getattr(p, 'fields', None)
                
                if fields:
                    attrs['fields'].update(fields)
        except NameError:
            pass
        
        meta = attrs.pop('Meta', None)
        translate = getattr(meta,'translate',())
        attrs['translate'] = translate

        for field_name, obj in attrs.items():
            if isinstance(obj, SearchField):
                field = attrs.pop(field_name)
                field.instance_name = field_name
                attrs['fields'][field_name] = field
                
                if field_name in translate:
                    # if this is a translated field, create clones of it for
                    # every language configured in settings.
                    # the clones are identical to the main field, but with
                    # "__xx" appendend (xx being the language code), and
                    # 'document' set to False.
                    for language in haystack.settings.LANGUAGES:
                        lang_field = field.__class__(
                            model_attr = field.model_attr,
                            use_template = field.use_template,
                            template_name = field.template_name,
                            document = False,
                            indexed = field.indexed,
                            stored = field.stored,
                            default = field.default,
                        )
                        lang_field.instance_name = field_name
                        attrs['fields']['__'.join([field_name,language[0]])] = lang_field
        
        return super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)


class SearchIndex(object):
    """
    Base class for building indexes.
    
    An example might look like this::
    
        import datetime
        from haystack import indexes
        from myapp.models import Note
        
        class NoteIndex(indexes.SearchIndex):
            text = indexes.CharField(document=True, use_template=True)
            author = indexes.CharField(model_attr='user')
            pub_date = indexes.DateTimeField(model_attr='pub_date')
            
            def get_query_set(self):
                return super(NoteIndex, self).get_query_set().filter(pub_date__lte=datetime.datetime.now())
    
    """
    __metaclass__ = DeclarativeMetaclass
    
    def __init__(self, model, backend=None):
        self.model = model
        self.backend = backend or haystack.backend.SearchBackend()
        self.prepared_data = None
        content_fields = []
        
        for field_name, field in self.fields.items():
            if field.document is True:
                content_fields.append(field_name)
        
        if not len(content_fields) == 1:
            raise SearchFieldError("An index must have one (and only one) SearchField with document=True.")

    
    def _setup_save(self, model):
        signals.post_save.connect(self.update_object, sender=model)
    
    def _setup_delete(self, model):
        signals.post_delete.connect(self.remove_object, sender=model)
    
    def _teardown_save(self, model):
        signals.post_save.disconnect(self.update_object, sender=model)
    
    def _teardown_delete(self, model):
        signals.post_delete.disconnect(self.remove_object, sender=model)
    
    def get_query_set(self):
        """
        Get the default QuerySet to index when doing a full update.
        
        Subclasses can override this method to avoid indexing certain objects.
        """
        return self.model._default_manager.all()
    
    def prepare(self, obj):
        """
        Fetches and adds/alters data before indexing.
        """
        self.prepared_data = {}
        from django.utils import translation
        
        for field_name, field in self.fields.items():
            try:
                basename,suffix = field_name.rsplit('__',1)
            except ValueError:
                basename,suffix = field_name,None

            if field_name in self.translate:
                # this is a translated field
                # the contents in all languages are joined together
                # and inserted into the field, so the object can
                # be found by search terms in any language
                self.prepared_data[field_name] = ''
                for language in haystack.settings.LANGUAGES:
                    translation.activate(language[0])
                    obj = self.model.objects.get(pk=obj.pk)
                    if hasattr(self, "prepare_%s" % field_name):
                        value = getattr(self, "prepare_%s" % field_name)(obj)
                        self.prepared_data[field_name] += ' '+ value
                    else:
                        self.prepared_data[field_name] += ' '+ field.prepare(obj)
            else:
                if suffix and (basename in self.translate):
                    # this is a clone of a translated field, it will hold
                    # the contents in the language corresponding the its suffix.
                    # to get the contents in the specific language, the locale is
                    # first activated, and then the object is fetched again from
                    # the database, because it is common to translate the model fields
                    # on object load and not on field access.
                    translation.activate(suffix)
                    obj = self.model.objects.get(pk=obj.pk)
                if hasattr(self, "prepare_%s" % basename):
                    value = getattr(self, "prepare_%s" % basename)(obj)
                    self.prepared_data[field_name] = value
                else:
                    self.prepared_data[field_name] = field.prepare(obj)

            translation.deactivate()

        return self.prepared_data
    
    def get_content_field(self):
        """Returns the field that supplies the primary document to be indexed."""
        for field_name, field in self.fields.items():
            if field.document is True:
                return field_name

    def update(self):
        """Update the entire index"""
        self.backend.update(self, self.get_query_set())

    def update_object(self, instance, **kwargs):
        """
        Update the index for a single object. Attached to the class's
        post-save hook.
        """
        # Check to make sure we want to index this first.
        if self.should_update(instance):
            self.backend.update(self, [instance])

    def remove_object(self, instance, **kwargs):
        """
        Remove an object from the index. Attached to the class's 
        post-delete hook.
        """
        self.backend.remove(instance)

    def clear(self):
        """Clear the entire index."""
        self.backend.clear(models=[self.model])

    def reindex(self):
        """Completely clear the index for this model and rebuild it."""
        self.clear()
        self.update()
    
    def get_updated_field(self):
        """
        Get the field name that represents the updated date for the model.
        
        If specified, this is used by the reindex command to filter out results
        from the QuerySet, enabling you to reindex only recent records. This
        method should either return None (reindex everything always) or a
        string of the Model's DateField/DateTimeField name.
        """
        return None
    
    def should_update(self, instance):
        """
        Determine if an object should be updated in the index.
        
        It's useful to override this when an object may save frequently and
        cause excessive reindexing. You should check conditions on the instance
        and return False if it is not to be indexed.
        
        By default, returns True (always reindex).
        """
        return True
    
    def load_all_queryset(self):
        """
        Provides the ability to override how objects get loaded in conjunction
        with ``SearchQuerySet.load_all``.
        
        This is useful for post-processing the results from the query, enabling
        things like adding ``select_related`` or filtering certain data.
        
        By default, returns ``all()`` on the model's default manager.
        """
        return self.model._default_manager.all()


class BasicSearchIndex(SearchIndex):
    text = CharField(document=True, use_template=True)
