#!/usr/bin/env python
import argparse
import glob
import os
import re
import logging
import pyperclip

import arxiv
import bibtexparser

import bibtexsanitizer


# initialize logging
logger = logging.getLogger('pybib')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


class Re:
    """Simple class to facilitate cascading through re.match expressions."""
    def __init__(self):
        self.last_match = None

    def match(self, pattern, text, *args):
        self.last_match = re.match(pattern, text, *args)
        return self.last_match

    def search(self, pattern, text, *args):
        self.last_match = re.search(pattern, text, *args)
        return self.last_match    

def _extract_doi_from_url(string):
    gre = Re()
    # strip initial url part, if present
    if gre.match(r'.*(?:doi\.org/)(.*)', string):
        return gre.last_match.group(1)
    elif gre.match(r'.*([0-9]{2}\.[0-9]{4}.*)', string):
        # e.g. revmodphys has these kinds of urls
        return gre.last_match.group(1)
    else:
        return string


def _extract_arxiv_id_from_url(string):
    gre = Re()
    # if already well formatted return untouched
    if gre.match(r'(^[0-9]{4}\.[0-9]+$)', string):
        return gre.last_match.group(1)
    # if the full new-style string was given, return id part
    elif gre.match(r'.*(?:pdf|abs)/([0-9]{4}\.[0-9]+).*', string):
        return gre.last_match.group(1)
    # old style string
    elif gre.match(r'.*(?:pdf|abs)/([a-zA-Z-]*/[0-9]*).*', string):
        return gre.last_match.group(1)
    # strings of the form arxiv:id or arxiv/id
    elif gre.match(r'.*arxiv(?::|/)([0-9]{4}\.[0-9]{4,5}).*', string, re.IGNORECASE):
        return gre.last_match.group(1)
    else:
        raise NotImplementedError('Unrecognised format')


def _add_reference_from_arxiv_id(bibfile, arxiv_ids):
    if isinstance(arxiv_ids, str):
        bibtexsanitizer.add_entry_from_arxiv_id(bibfile, arxiv_ids)
    else:
        bibtexsanitizer.add_entries_from_arxiv_ids(bibfile, arxiv_ids)


def _add_reference(bibfile, from_where, ids):
    if from_where == 'arxiv':
        ids = [_extract_arxiv_id_from_url(id_) for id_ in ids]
        _add_reference_from_arxiv_id(bibfile, ids)
    else:
        raise ValueError(
            '`{}` is not an acceptable command.'.format(from_where))


def _print_reference(from_where, identifiers):
    if from_where == 'arxiv':
        ids = [_extract_arxiv_id_from_url(id_) for id_ in identifiers]
        logger.info('I found the following arxiv ids in the given urls: {}'.format(ids))
        output = bibtexsanitizer.get_bibentry_from_arxiv_id(ids)
    elif from_where == 'doi':
        ids = [_extract_doi_from_url(id_) for id_ in identifiers]
        logger.info('I found the following dois in the given urls: {}'.format(ids))
        output = bibtexsanitizer.get_bibentry_from_doi(ids)
    else:
        raise NotImplementedError('To Be Done.')
    # copy to clipboard
    pyperclip.copy(output)
    # print to console
    print(output)

def _fix_bibfile(bibfile, method):
    if method != 'all':
        raise NotImplementedError('Just use `all` for now')
    bibtexsanitizer.fix_bibtex_syntax(bibfile, make_backup=True, method=method)


def _check_references(bibfile, what):
    if what == 'published':
        # check whether the entries with an arxiv id are associated with a
        # published journal
        db = bibtexsanitizer.load_bibtex_database(bibfile)
        for entry in db.entries:
            if (('journal' not in entry or 'doi' not in entry)
                    and 'eprint' in entry):
                details = bibtexsanitizer.pull_info_from_arxiv_id(
                    entry['eprint'])
                if 'doi' in details and 'doi' not in entry:
                    logger.info('Adding doi for {}'.format(entry['ID']))
                    entry['doi'] = details['doi']
                if 'journal' in details and 'journal' not in entry:
                    logger.info('Adding journal for {}'.format(entry['ID']))
                    entry['journal'] = details['journal']
        bibtexsanitizer.save_bibtex_database_to_file(bibfile, db)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manage bib files.')
    parser.add_argument('--bibfile', type=str, default='')
    subparsers = parser.add_subparsers()
    # parser for add reference command
    parser_add = subparsers.add_parser(
        'add', help='Add reference to bibliography.')
    parser_add.add_argument('where', type=str)
    parser_add.add_argument('ids', nargs='*')
    parser_add.add_argument('--action', type=str, default='add')
    # parser for print command
    parser_print = subparsers.add_parser(
        'print', help='Print to terminal the bibtex entry.')
    parser_print.add_argument('where', type=str)
    parser_print.add_argument('ids', nargs='*')
    parser_print.add_argument('--action', type=str, default='print')
    # parser for fix command
    parser_fix = subparsers.add_parser(
        'fix', help='Fix badly formatted bib files.')
    parser_fix.add_argument('method', type=str, nargs='?', default='all')
    parser_fix.add_argument('--action', type=str, default='fix')
    # parser for check command
    parser_check = subparsers.add_parser(
        'check', help='Check completeness of fields and other stuff.')
    parser_check.add_argument('what', type=str)
    parser_check.add_argument('--action', type=str, default='check')
    # parse the whole thing
    args = parser.parse_args()
    # the action argument must be defined
    if 'action' not in args:
        print('Run pybib -h for syntax help.')
        raise SystemExit()
    # decide where to save stuff, if needed
    if not args.bibfile and (args.action == 'add' or args.action == 'fix' or
                             args.action == 'check'):
        bibfiles = glob.glob('./*.bib')
        if not bibfiles:
            raise ValueError(
                'No bib file specified, and none found in the current directory.')
        elif len(bibfiles) > 1:
            raise ValueError('No bib file specified, and more than one found i'
                             'n the current directory, so I do not know which '
                             'one to use.')
        else:
            print('No bib file specified, using {}'.format(bibfiles[0]))
            bibfile = bibfiles[0]
    else:
        bibfile = args.bibfile
    # actually go with the parsing
    if args.action == 'add':
        _add_reference(bibfile, args.where, args.ids)
    elif args.action == 'print':
        _print_reference(args.where, args.ids)
    elif args.action == 'fix':
        _fix_bibfile(bibfile, args.method)
    elif args.action == 'check':
        _check_references(bibfile, args.what)
    else:
        raise ValueError('Unknown action.')
