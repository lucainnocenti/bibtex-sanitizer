import re
from collections import OrderedDict
from pprint import pprint
import copy
import logging

import sh
import arxiv
import bibtexparser
import pyparsing as pp


def load_bibtex_database(path):
    """Read .bib file and parse it using bibtexparser."""
    with open(path, encoding='utf-8') as f:
        bib_database = bibtexparser.load(f)
    return bib_database


def save_bibtex_database_to_file(path, db):
    """Save bibtexparser library object into file."""
    writer = bibtexparser.bwriter.BibTexWriter()
    writer.indent = '    '
    with open(path, 'w', encoding='utf-8') as f:
        f.write(writer.write(db))


def _load_or_use(path_or_db):
    """Load from file if input is a path, otherwise just use input as db."""
    if isinstance(path_or_db, str):
        path = path_or_db
        db = load_bibtex_database(path)
    else:
        path = None
        db = path_or_db
    return (path, db)


def _save_or_return(path_or_db, new_db):
    """
    If input was a string, save result to file, otherwise just return results.
    """
    if isinstance(path_or_db, str):
        save_bibtex_database_to_file(path_or_db, new_db)
        return None
    else:
        return new_db


def find_entries_without_field(path_or_db, field):
    """Return entries without field."""
    _, db = _load_or_use(path_or_db)
    lacking_entries = []
    for entry in db.entries:
        if field not in entry:
            lacking_entries += [entry]
    return lacking_entries


def remove_field_from_all_entries(path_or_db, fields):
    # if `database` is a string we assume it to be the path of the bib file
    if isinstance(path_or_db, str):
        path = path_or_db
        database = load_bibtex_database(path)
    else:
        path = None
        database = path_or_db
    # sanitize input parameter
    if isinstance(fields, str):
        fields = [fields]
    if not isinstance(fields, (list, tuple)):
        raise ValueError('`fields` should be a list or tuple')
    # remove unwanted fields
    for entry in database.entries:
        for field in fields:
            entry.pop(field, None)
    # save or return result
    if path is not None:
        save_bibtex_database_to_file(path, database)
    else:
        return database


def fix_records_without_brackets(path):
    """Fix bad fields in bib file."""
    # Records sometimes do not include parenthesis, which trips bibtexparser up,
    # this fixes these entries
    with open(path, encoding='utf-8') as f:
        text = f.read()
    newtext = re.sub(r'\s?([a-z]*)\s?=\s?([0-9a-z]*),',
                     r'    \1 = {\2},',
                     text)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(newtext)


def reformat_file(path):
    """Load and resave file, fixing some formatting issues in the process."""
    bib_database = load_bibtex_database(path)
    save_bibtex_database_to_file(path, bib_database)


def _is_newstyle_arxiv_id(arxiv_number):
    """Check whether arxiv id is old or new style (or invalid)."""
    if re.match(r'^[0-9]{4}\.[0-9]*$', arxiv_number):
        return True
    if re.match(r'^[a-z]*-[a-z]*/[0-9]*$', arxiv_number):
        return False
    raise ValueError('Not a proper arxiv id')


def pull_info_from_doi(doi, accepted_fields=None):
    """Pull down paper info using its DOI identifier."""
    ans = sh.curl('-LH', r'Accept: text/bibliography; style=bibtex',
                  r'http://dx.doi.org/' + doi)
    ans = ans.stdout.decode('UTF-8')
    if accepted_fields is None:
        accepted_fields = ['title', 'volume', 'year', 'number', 'journal',
                           'publisher', 'month', 'author', 'doi']
    details = {}
    for field in accepted_fields:
        value = re.search(field + r'={([^}]*)}', ans)
        if value:
            details[field] = value[1]
    details['doi'] = doi
    return details


def pull_info_from_arxiv_id(arxiv_id, requested_fields=None, use_doi=True):
    """Pull down paper info from arxiv id."""
    ans = arxiv.query(id_list=[arxiv_id])
    if not ans:
        logging.warning('No paper found with the ID {}.'.format(arxiv_id))
    ans = ans[0]
    # extract fields
    details = extract_fields_from_arxiv_query_result(
        ans, requested_fields=requested_fields, use_doi=use_doi)
    return details


def authors_list_to_string(authors):
    """Take list of authors full names and return author string for bibtex."""
    authors_strings = []
    for author in authors:
        names = author.split(' ')
        last_name = names[-1]
        authors_strings.append(last_name + ', ' + ' '.join(names[:-1]))
    return ' and '.join(authors_strings)


def extract_fields_from_arxiv_query_result(result, requested_fields=None,
                                           use_doi=True):
    """Take the answer of an arxiv query and extract relevant fields from it.
    """
    if requested_fields is None:
        requested_fields = ['title', 'authors', 'doi', 'year']
    fields = dict()
    # extract generic fields
    for field in requested_fields:
        # the arxiv api calles the set of authors `authors`, while bibtex uses
        # the key `author`
        if field == 'authors':
            fields['author'] = result[field]
        elif field == 'year':
            fields['year'] = str(result['published_parsed'][0])
        else:
            fields[field] = result[field]
    # extract arxiv id info
    arxiv_number = re.search('arxiv.org/abs/([^v]*)', result['id']).group(1)
    newstyle = _is_newstyle_arxiv_id(arxiv_number)
    if newstyle:
        fields.update(dict(
            archiveprefix='arXiv',
            primaryclass=result['tags'][0]['term'],
            eprint=arxiv_number
        ))
    else:
        fields.update(dict(
            eprint=arxiv_number
        ))
    # if requested, try to use the doi to extract additional information
    if use_doi and fields['doi']:
        fields.update(pull_info_from_doi(fields['doi']))
    else:
        # if no doi is used, we need to reformat the `author` entry, to convert
        # it from a list of authors to a single string with all the authors
        fields['author'] = authors_list_to_string(fields['author'])
    # return results
    return fields


def arxiv_query_title(title):
    """Query arxiv for papers with given title."""
    query = 'ti:"{}"'.format(title.replace('-', ' '))
    return arxiv.query(search_query=query)


def _has_journal_arxiv_field(db_entry):
    """Check whether entry has a journal field containing arxiv info."""
    if 'journal' not in db_entry:
        return False
    journal = db_entry['journal']
    # this detects entries coming from google scholar
    if journal[:5] != 'arXiv':
        return False
    patt = r'arXiv preprint arXiv:([0-9]{4}\.[0-9]*)$'
    match = re.match(patt, journal)
    if not match:
        return False
    return match.group(1)


def fill_bibdatabase_arxiv_entries(db, max_processed_entries=None, force=False):
    """Use titles to try to fill in the arxiv details."""
    num_processed_entries = 0
    for entry in db.entries:
        # if an eprint entry already exists, don't touch anything
        if 'eprint' in entry and not force:
            continue

        arxiv_id = _has_journal_arxiv_field(entry)
        if arxiv_id:
            print('Found id {} in journal entry, using this'.format(arxiv_id))
            print('Deleting journal field from this entry')
            del entry['journal']
            answers = arxiv.query(id_list=[arxiv_id])
        else:
            answers = arxiv_query_title(entry['title'])
        # if we get more than one answer from the arxiv, we look for one with
        # an exactly matching title. If none is found, do nothing.
        if len(answers) > 1:
            logging.info('{}: Found more than one result'.format(entry['ID']))
            for ans in answers:
                if ans['title'] == entry['title']:
                    answer = [ans]
                else:
                    continue
        elif len(answers) == 0:
            logging.info('{}: No results'.format(entry['ID']))
            continue
        answer = answers[0]
        fields_to_add = extract_fields_from_arxiv_query_result(answer)
        entry.update(fields_to_add)
        logging.info('Updated {}'.format(entry['ID']))
        # abort if maximum number of entries to process has been reached
        if max_processed_entries is not None:
            num_processed_entries += 1
            if num_processed_entries == max_processed_entries:
                print('Processed {} entries. Stopping as requested.'.format(
                    num_processed_entries))
                return


def update_entry_from_doi(entry):
    """Refill entry fields using its DOI."""
    if 'doi' not in entry:
        return entry
    accepted_fields = ['title', 'volume', 'year', 'number', 'journal',
                       'publisher', 'month']
    new_fields = pull_info_from_doi(entry['doi'], accepted_fields)
    entry.update(new_fields)
    return entry


def update_entries_from_doi(path_or_db):
    # parsing input parameters
    if isinstance(path_or_db, str):
        path = path_or_db
        db = load_bibtex_database(path_or_db)
    else:
        path = None
        db = path_or_db
    # doing the deed
    for entry in db.entries:
        update_entry_from_doi(entry)
    # save or return result
    if path:
        save_bibtex_database_to_file(path, db)
    else:
        return db


def check_id_style(path_or_db, style='gscholar'):
    if isinstance(path_or_db, str):
        db = load_bibtex_database(path_or_db)
    else:
        db = path_or_db

    if style != 'gscholar':
        raise ValueError('Only google scholar style works for now.')
    everything_good = True
    for entry in db.entries:
        ID = entry['ID']
        if style == 'gscholar':
            matcher = re.compile(r'[a-z]*[0-9]{4}[a-z]*$')
        match = matcher.match(ID)
        if not match:
            everything_good = False
            print('{} does not match the ID style.'.format(ID))
    return everything_good


def check_fields(path_or_db, fields=None):
    """Prints all entries not containing one of the specified fields."""
    if isinstance(path_or_db, str):
        db = load_bibtex_database(path_or_db)
    else:
        db = path_or_db

    for entry in db.entries:
        for field in fields:
            if field not in entry:
                print('{} is missing the {}'.format(entry['ID'], field))


def make_id_for_entry(entry, style='gscholar'):
    """Take entry as a dict, and return an ID to use for the bib entry."""
    if style != 'gscholar':
        raise NotImplementedError('Not implemented yet.')
    if not (entry['author'] and entry['title'] and entry['year']):
        raise ValueError("author, title and year are required.")
    title = entry['title']
    year = entry['year']
    author = entry['author'].split(',')[0].lower()
    # extract first author
    if author[0] == '{':
        author = author[1:]
    if author[-1] == '}':
        author = author[:-1]
    if ' ' in author:
        author = author.split(' ')[0]
    # extract first word
    first_word = title.split(' ')[0].lower()
    if first_word[0] == '{':
        first_word = first_word[1:]
    if first_word[-1] == '}':
        first_word = first_word[:-1]
    if '-' in first_word:
        first_word = first_word.split('-')[0]
    # build new id
    newid = '{}{}{}'.format(author, year, first_word)
    logging.info('New id: {}'.format(newid))
    return newid


def fix_ids_to_scholar_style(path):
    """Fix entries ids to match the google scholar format."""
    db = load_bibtex_database(path)
    for entry in db.entries:
        ID = entry['ID']
        scholar_style = re.match(r'[a-z]*[0-9]{4}[a-z]*$', ID)
        if not scholar_style:
            logging.info('Processing {}'.format(ID))
            newid = make_id_for_entry(entry)
            # check that the new ID doesn't already exists
            if any(entry['ID'] == newid for entry in db.entries):
                print(entry['ID'], newid)
                raise ValueError('There is already an entry with this ID, '
                                 'there may be something wrong!')
            entry['ID'] = newid
    save_bibtex_database_to_file(path, db)


def make_bibentry_from_arxiv_id(arxiv_id):
    """Build bib entry from a single arxiv id."""
    entry = pull_info_from_arxiv_id(arxiv_id)
    entry['ENTRYTYPE'] = 'article'
    entry['ID'] = make_id_for_entry(entry)
    return entry


def make_bibentry_from_doi(doi):
    """Build bib entry from a DOI."""
    entry = pull_info_from_doi(doi)
    entry['ENTRYTYPE'] = 'article'
    entry['ID'] = make_id_for_entry(entry)
    return entry


def add_entry_from_arxiv_id(path_or_db, arxiv_id, force=False):
    """Build entry corresponding to arxiv id, and add it to bib database."""
    # parse input parameteres
    if isinstance(path_or_db, str):
        path = path_or_db
        db = load_bibtex_database(path_or_db)
    else:
        path = None
        db = path_or_db
    old_db = copy.deepcopy(db)
    # check whether entry already exists
    if not force:
        for entry in db.entries:
            if 'eprint' in entry and entry['eprint'] == arxiv_id:
                logging.info('An entry with arxiv id {} already exists.'.format(
                    arxiv_id))
                if path:
                    return None
                else:
                    return db
    # do the thing
    newentry = make_bibentry_from_arxiv_id(arxiv_id)
    # empty fields will throw errors, so we remove them
    if not newentry['doi']:
        del newentry['doi']
    # add new entry to database
    db.entries.append(newentry)
    # save or return output
    if path:
        try:
            save_bibtex_database_to_file(path, db)
        except:
            save_bibtex_database_to_file(path, old_db)
            raise
    else:
        return db


def add_entries_from_arxiv_ids(path_or_db, arxiv_ids):
    """Take list of arxiv ids and build corresponding entries."""
    _, db = _load_or_use(path_or_db)
    # do the thing
    for arxiv_id in arxiv_ids:
        db = add_entry_from_arxiv_id(db, arxiv_id)
    # save or return result
    _save_or_return(path_or_db, db)


def add_entry_from_doi(path_or_db, doi):
    """Add an entry retrieved from a doi identifier."""
    _, db = _load_or_use(path_or_db)
    # check whether entry already exists
    for entry in db.entries:
        if 'doi' in entry and entry['doi'] == doi:
            logging.info('An entry with doi {} already exists.'.format(doi))
            return db
    # do the thing
    newentry = make_bibentry_from_doi(doi)
    db.entries.append(newentry)
    # save or return output
    _save_or_return(path_or_db, db)

