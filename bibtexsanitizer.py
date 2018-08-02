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


def find_entries_without_field(database, field):
    """Return entries without field."""
    # if `database` is a string we assume it to be the path of the bib file
    if isinstance(database, str):
        database = load_bibtex_database(database)
    # otherwise we assume `database` to be a bibtexparser database object
    lacking_entries = []
    for entry in database.entries:
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


def extract_fields_from_arxiv_query_result(result):
    fields = dict()
    # extract doi if there is one
    if result['doi']:
        print(result['id'], result['doi'])
        fields['doi'] = result['doi']
    # extract arxiv info
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
    ans = sh.curl('-LH', r'Accept: text/bibliography; style=bibtex',
                  r'http://dx.doi.org/' + entry['doi']).stdout
    ans = ans.decode('UTF-8')
    accepted_fields = ['title', 'volume', 'year', 'number', 'journal',
                       'publisher', 'month']
    new_fields = {}
    for field in accepted_fields:
        value = re.search(field + r'={([^}]*)}', ans)
        if value:
            new_fields[field] = value[1]
    entry.update(new_fields)
    return entry


def update_entries_from_doi(path_or_db):
    if isinstance(path_or_db, str):
        path = path_or_db
        db = load_bibtex_database(path_or_db)
    else:
        path = None
        db = path_or_db
    for entry in db.entries:
        update_entry_from_doi(entry)
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


def fix_ids_to_scholar_style(path):
    """Fix entries ids to match the google scholar format."""
    db = load_bibtex_database(path)
    for entry in db.entries:
        ID = entry['ID']
        title = entry['title']
        scholar_style = re.match(r'[a-z]*[0-9]{4}[a-z]*$', ID)
        if not scholar_style:
            logging.info('Processing {}'.format(ID))
            if 'year' not in entry:
                raise ValueError('Need year field to set entry')
            author = entry['author'].split(',')[0].lower()
            # sometimes the author names are surrounded with brackets
            if author[0] == '{':
                author = author[1:]
            if author[-1] == '}':
                author = author[:-1]
            # if there were spaces inside a bracket, remove them
            if ' ' in author:
                author = author.split(' ')[0]
            year = entry['year']
            first_word = title.split(' ')[0].lower()
            if first_word[0] == '{':
                first_word = first_word[1:]
            if first_word[-1] == '}':
                first_word = first_word[:-1]
            newid = '{}{}{}'.format(author, year, first_word)
            logging.info('New id: {}'.format(newid))
            # check that the new ID doesn't already exists
            if any(entry['ID'] == newid for entry in db.entries):
                print(entry['ID'], newid)
                raise ValueError(
                    'There is already an entry with this ID, there may be something wrong!')
            entry['ID'] = newid
    save_bibtex_database_to_file(path, db)
