import copy
import logging
import os
import re
import shutil
from collections import OrderedDict
from pprint import pprint

import arxiv
import bibtexparser
import pyparsing as pp
import sh

import utils


logger = utils.initialize_logging('pybib')


class DOIError(Exception):
    pass


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
        shutil.copyfile(path, path + '.bak')
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
        os.remove(path_or_db + '.bak')
        return None
    else:
        return new_db


def _fix_month_fields(text, action='strtoint'):
    """Convert all month fields from string to numeric format."""
    months_strings = ['jan', 'feb', 'mar', 'may', 'jun', 'jul', 'aug', 'sep',
                      'oct', 'nov', 'dec']
    for month_str in months_strings:
        patt = r'month\s*=\s*{{{}}}'.format(month_str)
        text = re.sub(patt, newpatt, flags=re.I)


def fix_bibtex_syntax(path, make_backup=True, method='all'):
    """Fix bad fields in bib file."""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if make_backup:
        backup_file = path + '.old'
        logger.info('Saving backup file at `{}`...'.format(backup_file))
        shutil.copyfile(path, backup_file)
    # fix fields without curly braces for value
    logger.info('Ensuring all fields have curly braces...')
    newtext = re.sub(r'([a-z]*)\s*=\s*([^\s{].*)(,\n|\s*})',
                     r'\1 = {\2}\3',
                     text)
    # fix title fields with double curly braces
    logger.info('Ensuring titles dont\'t have *double* curly braces (because that\'s just horrible)...')
    newtext = re.sub(r'title\s*=\s*{{([^}]*)}}(,\s*\n|\s*})',
                     r'title = {\1}\2',
                     newtext)
    logger.info('Ensuring months fields are in numeric format...')
    newtext = _fix_month_fields(newtext, action='strtoint')

    # save results
    with open(path, 'w', encoding='utf-8') as f:
        f.write(newtext)
    # do addition house cleaning
    if method == 'all':
        fields_to_remove = ['file', 'abstract', 'arxivid']
        logger.info('Removing unnecessary fields: {}...'.format(', '.join(fields_to_remove)))
        remove_field_from_all_entries(path, fields_to_remove)
        logger.info('Checking fields consistency...')
        check_arxiv_fields_consistency(path, fix=True)
    logger.info('All done! You\'re good to go.')


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
        accepted_fields = ['title', 'year', 'volume', 'number', 'pages', 'ISBN',
                           'journal', 'publisher', 'month', 'author', 'doi']
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
        logger.error('No paper found with the ID {}.'.format(arxiv_id))
    ans = ans[0]
    # extract fields
    details = extract_fields_from_arxiv_query_result(
        ans, requested_fields=requested_fields, use_doi=use_doi)
    return details


def pull_info_from_gscholar(query, accepted_fields=None):
    """Look for entry in google scholar."""
    import gscholar
    bibtex_string = gscholar.query(query)[0]
    if accepted_fields is None:
        accepted_fields = ['title', 'year', 'volume', 'number', 'pages', 'ISBN',
                           'journal', 'publisher', 'month', 'author', 'doi']
    details = {}
    for field in accepted_fields:
        value = re.search(field + r'={([^}]*)}', bibtex_string)
        if value:
            details[field] = value[1]
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
        requested_fields = ['title', 'authors', 'doi', 'year',
                            'journal_reference']
    fields = dict()
    # extract generic fields
    for field in requested_fields:
        # the arxiv api calles the set of authors `authors`, while bibtex uses
        # the key `author`. Similar adjustments have to be made for other fields
        if field == 'authors':
            fields['author'] = result[field]
        elif field == 'year':
            fields['year'] = str(result['published_parsed'][0])
        elif field == 'journal_reference':
            fields['journal'] = result[field]
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
    if not fields['doi']:
        del fields['doi']
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
            logger.info('{}: Found more than one result'.format(entry['ID']))
            for ans in answers:
                if ans['title'] == entry['title']:
                    answer = [ans]
                else:
                    continue
        elif len(answers) == 0:
            logger.info('{}: No results'.format(entry['ID']))
            continue
        answer = answers[0]
        fields_to_add = extract_fields_from_arxiv_query_result(answer)
        entry.update(fields_to_add)
        logger.info('Updated {}'.format(entry['ID']))
        # abort if maximum number of entries to process has been reached
        if max_processed_entries is not None:
            num_processed_entries += 1
            if num_processed_entries == max_processed_entries:
                print('Processed {} entries. Stopping as requested.'.format(
                    num_processed_entries))
                return


def _update_entry_from_doi(entry):
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
    _, db = _load_or_use(path_or_db)
    # doing the deed
    for entry in db.entries:
        _update_entry_from_doi(entry)
    # save or return result
    return _save_or_return(path_or_db, db)


def check_id_style(path_or_db, style='gscholar'):
    """Makes sure that all entries' ids follows the correct style."""
    if isinstance(path_or_db, str):
        db = load_bibtex_database(path_or_db)
    else:
        db = path_or_db

    if style != 'gscholar':
        raise ValueError('Only google scholar style supported at the moment.')
    all_good = True
    for entry in db.entries:
        ID = entry['ID']
        if style == 'gscholar':
            matcher = re.compile(r'[a-z]*[0-9]{4}[a-z]*$')
        match = matcher.match(ID)
        if not match:
            all_good = False
            print('{} does not match the ID style.'.format(ID))
    return all_good


def _fix_key_casing(entry, correct_string):
    if correct_string in entry:
        return None

    wrong_key = None
    for key in entry.keys():
        if key.lower() == correct_string.lower():
            wrong_key = key
    # is an incorrectly cased key was indeed found, amend the mistake
    if wrong_key is not None:
        entry[correct_string] = entry[wrong_key]
        del entry[wrong_key]
    # return result
    return entry


def check_arxiv_fields_consistency(path_or_db, fix=True, assume_arxiv=True, assume_quantph=True):
    """Makes sure that all arxiv entries follow the correct format.

    The correct format is here assumed to be:
    1) For new-style eprints:
        archivePrefix = {arXiv},
        eprint = {0902.0885},
        primaryClass = {quant-ph}
    2) For old-style eprints:
        archivePrefix = {arXiv},
        eprint = {quant-ph/0401062}


    If the `fix` parameter is given, attempts are made to fix inconsistencies.

    The `assume_arxiv` parameter has the parser assume that all eprint entries are
    supposed to refer to arxiv eprints.

    If assume_quantph is True then the primaryClass will be automatically set to quant-ph, if missing.
    """
    _, db = _load_or_use(path_or_db)

    for entry in db.entries:
        # sometimes the 'archivePrefix' and 'primaryClass' entries exist but are not properly cased. Fix this
        entry = _fix_key_casing(entry, 'archivePrefix')
        entry = _fix_key_casing(entry, 'primaryClass')
        # if there is a 'eprint' entry but not a 'archivePrefix' one, things
        # are probably wrong
        if 'eprint' in entry and 'archivePrefix' not in entry:
            if not assume_arxiv:
                print("The entry '{}' is probably missing the 'archivePrefix' field."
                      " (has to be fixed manually).".format(entry['ID']))
            else:
                print("Adding 'archivePrefix' field to the entry '{}'".format(
                    entry['ID']))
                entry['archivePrefix'] = 'arXiv'
        # if the archivePrefix field is given and indicating an arxiv entry...
        if 'archivePrefix' in entry and entry['archivePrefix'] == 'arXiv':
            if 'eprint' not in entry:
                print("The entry '{}' is missing the 'eprint' field."
                      " (has to be fixed manually).".format(entry['ID']))
            else:
                arxiv_entry_style = None
                # check correct format of the eprint entry
                if re.match(r'[0-9]{4}\.[0-9]{4,5}$', entry['eprint']):
                    arxiv_entry_style = 'new'
                    if 'primaryClass' not in entry and not assume_quantph:
                        print("The entry '{}' is missing the 'primaryClass' field"
                              " (has to be fixed manually).".format(entry['ID']))
                    elif 'primaryClass' not in entry and assume_quantph:
                        print("Adding 'quant-ph' as primaryClass for the '{}' entry.".format(
                            entry['ID']))
                        entry['primaryClass'] = 'quant-ph'
                elif re.match(r'[a-z-]+/[0-9]+$', entry['eprint']):
                    arxiv_entry_style = 'old'
                    if 'primaryClass' in entry:
                        print("The entry '{}' should NOT have a 'primaryClass' field"
                              " (has to be fixed manually).".format(entry['ID']))
                else:
                    print("The entry '{}' is using an incorrectly formatted 'eprint' field"
                          " (has to be fixed manually).".format(entry['ID']))

    return _save_or_return(path_or_db, db)


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
    try:
        entry['title']
    except KeyError:
        raise KeyError('No dice without a title!')
    try:
        entry['author']
        entry['year']
    except KeyError:
        # try to pull down additional information from google scholar
        logger.info('I could not find author/year information from DOI/arxiv,'
                     ' attempting to pull information down from gscholar.')
        gscholar_result = pull_info_from_gscholar(
            entry['title'], accepted_fields=['author', 'year'])
        if 'author' in gscholar_result and 'year' in gscholar_result:
            logger.info('Author/year information pulled from scholar.')
            entry.update(gscholar_result)
        else:
            raise KeyError("author, title and year are required.")
    title = entry['title']
    logger.info('I found the title "{}"'.format(title))
    year = entry['year']
    author = entry['author'].split(',')[0].lower()
    # extract first author
    if author[0] == '{':
        author = author[1:]
    if author[-1] == '}':
        author = author[:-1]
    if ' ' in author:
        author = author.split(' ')[0]
    # extract first word (looking at "words" with more than 3 chars)
    words_in_title = re.findall(r'\S+', title)
    words_in_title = [w for w in words_in_title if len(w) > 3]
    first_word = words_in_title[0].lower()
    if first_word[0] == '{':
        first_word = first_word[1:]
    if first_word[-1] == '}':
        first_word = first_word[:-1]
    if '-' in first_word:
        first_word = first_word.split('-')[0]
    # build new id
    newid = '{}{}{}'.format(author, year, first_word)
    logger.info('New id for the given entry: `{}`'.format(newid))
    return newid


def fix_ids_to_scholar_style(path):
    """Fix entries ids to match the google scholar format."""
    db = load_bibtex_database(path)
    for entry in db.entries:
        ID = entry['ID']
        scholar_style = re.match(r'[a-z]*[0-9]{4}[a-z]*$', ID)
        if not scholar_style:
            logger.info('Processing {}'.format(ID))
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
    """Build bib entry from a single DOI."""
    entry = pull_info_from_doi(doi)
    entry['ENTRYTYPE'] = 'article'
    try:
        entry['ID'] = make_id_for_entry(entry)
    except DOIError:
        logger.debug('Full entry:')
        logger.debug(entry)
        raise DOIError('Something went wrong while fetching'
                         ' the id to use for the doi "{}". Probably,'
                         ' the DOI database does not hold enough information'
                         ' about the paper (it often lacks a title).'.format(doi))
    return entry


def get_bibentry_from_doi(dois):
    """Return the bibtex entry corresponding to the given doi, as a string.
    
    The actual heavy lifting is done by `make_bibentry_from_doi`, here we just
    check the input, warn the logger, and call `make_bibentry_from_doi` as
    suitable.
    """
    if isinstance(dois, str):
        logger.info('Making bib entry for the doi "{}"'.format(dois))
        entries = [make_bibentry_from_doi(dois)]
    else:  # we assume it's a list of strings otherwise
        entries = []
        for doi in dois:
            logger.info('Making bib entry for the doi "{}"'.format(doi))
            entries.append(make_bibentry_from_doi(doi))
    # build the db using the entries
    return _print_bibtex_string_from_entries(entries)


def _print_bibtex_string_from_entries(entries):
    # build the db using the entries
    db = bibtexparser.bibdatabase.BibDatabase()
    db.entries = entries
    # prepare and print results
    writer = bibtexparser.bwriter.BibTexWriter()
    writer.indent = '    '
    return writer.write(db)


def get_bibentry_from_arxiv_id(arxiv_ids):
    """Return the bibtex entry corresponding to an arxiv id as a string."""
    if isinstance(arxiv_ids, str):
        entries = [make_bibentry_from_arxiv_id(arxiv_ids)]
    else:
        entries = []
        for arxiv_id in arxiv_ids:
            entries.append(make_bibentry_from_arxiv_id(arxiv_id))
    # build the db using the entries
    return _print_bibtex_string_from_entries(entries)



def add_entry_from_arxiv_id(path_or_db, arxiv_id, force=False):
    """Build entry corresponding to arxiv id, and add it to bib database."""
    # parse input parameteres
    path, db = _load_or_use(path_or_db)
    # check whether entry already exists
    if not force:
        for entry in db.entries:
            if 'eprint' in entry and entry['eprint'] == arxiv_id:
                logger.info('An entry with arxiv id {} already exists.'.format(
                    arxiv_id))
                if path:
                    return None
                else:
                    return db
    # do the thing
    newentry = make_bibentry_from_arxiv_id(arxiv_id)
    # add new entry to database
    db.entries.append(newentry)
    # save or return output
    return _save_or_return(path_or_db, db)


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
            logger.info('An entry with doi {} already exists.'.format(doi))
            return db
    # do the thing
    newentry = make_bibentry_from_doi(doi)
    db.entries.append(newentry)
    # save or return output
    _save_or_return(path_or_db, db)
