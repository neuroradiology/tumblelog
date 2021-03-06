#!/usr/bin/env python3
#
# (c) John Bokma, 2019
#
# This program is free software; you can redistribute it and/or modify it
# under the same terms as Python itself.

import re
import sys
import json
import argparse
import urllib.parse
from html import escape
from operator import itemgetter
from pathlib import Path
from datetime import datetime
from collections import defaultdict, deque
from commonmark import commonmark

VERSION = '1.0.3'

RE_WEEK = re.compile(r'%V')
RE_YEAR = re.compile(r'%Y')

RE_TITLE      = re.compile(r'(?x) \[% \s* title      \s* %\]')
RE_YEAR_RANGE = re.compile(r'(?x) \[% \s* year-range \s* %\]')
RE_LABEL      = re.compile(r'(?x) \[% \s* label      \s* %\]')
RE_CSS        = re.compile(r'(?x) \[% \s* css        \s* %\]')
RE_NAME       = re.compile(r'(?x) \[% \s* name       \s* %\]')
RE_AUTHOR     = re.compile(r'(?x) \[% \s* author     \s* %\]')
RE_VERSION    = re.compile(r'(?x) \[% \s* version    \s* %\]')
RE_FEED_URL   = re.compile(r'(?x) \[% \s* feed-url   \s* %\]')
RE_BODY       = re.compile(r'(?x) \[% \s* body       \s* %\] \n')
RE_ARCHIVE    = re.compile(r'(?x) \[% \s* archive    \s* %\] \n')


class NoEntriesError(Exception):
    """Thrown in case there are no blog entries; the file is empty"""

class NoDateSpecified(Exception):
    """Thrown in case the first blog entry has no date"""


def join_year_week(year, week):
    return f'{year:04d}-{week:02d}'

def split_year_week(year_week):
    return year_week.split('-')

def split_date(date):
    return date.split('-')

def parse_date(str):
    return datetime.strptime(str, '%Y-%m-%d')

def year_week_label(format, year, week):
    str = RE_WEEK.sub(week, format)
    str = RE_YEAR.sub(year, str)
    return str

def get_year_week(date):
    dt = parse_date(date)
    return join_year_week(*dt.isocalendar()[0:2])

def read_tumblelog_entries(filename):
    with open(filename, encoding='utf8') as f:
        entries = [item for item in f.read().split('%\n') if item]
    if not entries:
        raise NoEntriesError('No blog entries found')

    return entries

def collect_days(entries):
    pattern = re.compile(r'(\d{4}-\d{2}-\d{2})(.*?)\n(.*)', flags=re.DOTALL)
    date = None
    days = deque()
    for entry in entries:
        match = pattern.match(entry)
        if match:
            date = match.group(1)
            days.append({
                'date': date,
                'title': match.group(2).strip(),
                'entries': []
            })
            entry = match.group(3)
        if date is None:
            raise NoDateSpecified('No date specified for first tumblelog entry')

        days[-1]['entries'].append(entry)

    days = sorted(days, key=itemgetter('date'), reverse=True)

    return days

def create_archive(days):

    seen = {}
    archive = defaultdict(deque)
    for day in days:
        dt = parse_date(day['date'])
        year, week = dt.isocalendar()[0:2]
        year_week = join_year_week(year, week)
        if year_week not in seen:
            archive[f'{year:04d}'].appendleft(f'{week:02d}')
            seen[year_week] = 1

    return archive

def html_link_for_day(day, config):

    title = escape(day['title'])
    label = escape(parse_date(day['date']).strftime(config['date-format']))
    if not title:
        title = label

    year, month, day_number = split_date(day['date'])
    uri = f'../../{year}/{month}/{day_number}.html'

    return f'<a href="{uri}" title="{label}">{title}</a>'

def html_for_next_prev(days, index, config):

    length = len(days)
    if length == 1:
        return ''

    html = '<nav class="tl-next-prev">\n'

    if index:
        html += ''.join([
            '  <div class="next">',
            html_link_for_day(days[index - 1], config),
            '</div>',
            '<div class="tl-right-arrow">\u2192</div>\n'
        ])

    if index < length - 1:
        html += ''.join([
            '  <div class="tl-left-arrow">\u2190</div>',
            '<div class="prev">',
            html_link_for_day(days[index + 1], config),
            '</div>\n'
        ])

    html += '</nav>\n'

    return html

def html_for_archive(archive, current_year_week, path, label_format):
    html = '<nav>\n  <dl class="tl-archive">\n'
    for year in sorted(archive.keys(), reverse=True):
        html += f'    <dt>{year}</dt>\n    <dd>\n      <ul>\n'
        for week in archive[year]:
            year_week = join_year_week(int(year), int(week))
            if current_year_week is not None and year_week == current_year_week:
                html += f'        <li class="tl-self">{week}</li>\n'
            else:
                title = escape(year_week_label(label_format, year, week))
                uri = f'{path}/{year}/week/{week}.html'
                html += ''.join([
                    '        <li>',
                    f'<a href="{uri}" title="{title}">{week}</a></li>\n'
                ])
        html += '      </ul>\n    </dd>\n'
    html += '  </dl>\n</nav>\n'

    return html

def html_for_date(date, date_format, path):
    year, month, day = date.split('-')
    uri = f'{path}/{year}/{month}/{day}.html'

    return ''.join([
        f'<time class="tl-date" datetime="{date}"><a href="{uri}">',
        parse_date(date).strftime(date_format),
        '</a></time>\n'
    ])

def html_for_entry(entry):
    return ''.join([
        '<article>\n',
        commonmark(entry),
        '</article>\n'
    ])

def label_and_title(day, config):
    label = parse_date(day['date']).strftime(config['date-format'])
    title = day['title']
    if title:
        title = ' - '.join([title, config['name']])
    else:
        title = ' - '.join([config['name'], label])

    return label, title

def create_page(path, title, body_html, archive_html, config,
                label, min_year, max_year):
    if min_year == max_year:
        year_range = min_year
    else:
        year_range = f'{min-year}\u2013{max_year}'

    slashes = path.count('/')
    css = ''.join(['../' * slashes, config['css']])

    html = config['template']
    html = RE_TITLE.sub(escape(title), html)
    html = RE_YEAR_RANGE.sub(escape(year_range), html)
    html = RE_LABEL.sub(escape(label), html)
    html = RE_CSS.sub(escape(css), html)
    html = RE_NAME.sub(escape(config['name']), html)
    html = RE_AUTHOR.sub(escape(config['author']), html)
    html = RE_VERSION.sub(escape(VERSION), html)
    html = RE_FEED_URL.sub(escape(config['feed-url']), html)
    html = RE_BODY.sub(lambda x: body_html, html, count=1)
    html = RE_ARCHIVE.sub(archive_html, html)

    Path(config['output-dir']).joinpath(path).write_text(
        html, encoding='utf-8')

    if not config['quiet']:
        print(f"Created '{path}'")

def create_index(days, archive, config, min_year, max_year):
    body_html = ''
    todo = config['days']

    for day in days:
        body_html += html_for_date(
            day['date'], config['date-format'], 'archive'
        )
        for entry in day['entries']:
            body_html += html_for_entry(entry)
        todo -= 1
        if not todo:
            break

    archive_html = html_for_archive(
        archive, None, 'archive', config['label-format'])

    label = 'home'
    title = ' - '.join([config['name'], label])

    Path(config['output-dir']).mkdir(parents=True, exist_ok=True)
    create_page(
        'index.html', title, body_html, archive_html, config,
        label, min_year, max_year
    )

def create_week_page(year_week, body_html, archive, config, min_year, max_year):

    archive_html = html_for_archive(
        archive, year_week, '../..', config['label-format'])

    year, week = split_year_week(year_week)
    label = year_week_label(config['label-format'], year, week)
    title = ' - '.join([config['name'], label])

    path = f'archive/{year}/week'
    Path(config['output-dir']).joinpath(path).mkdir(
        parents=True, exist_ok=True)
    create_page(
        path + f'/{week}.html',
        title, body_html, archive_html, config,
        label, min_year, max_year
    )

def create_day_and_week_pages(days, archive, config, min_year, max_year):

    week_body_html = ''
    current_year_week = get_year_week(days[0]['date'])
    day_archive_html = html_for_archive(
        archive, None, '../..', config['label-format'])
    index = 0
    for day in days:
        day_body_html = html_for_date(
            day['date'], config['date-format'], '../..'
        )
        for entry in day['entries']:
            day_body_html += html_for_entry(entry)
            label, title = label_and_title(day, config)
            year, month, day_number = split_date(day['date'])
            next_prev_html = html_for_next_prev(days, index, config)

        path = f'archive/{year}/{month}'
        Path(config['output-dir']).joinpath(path).mkdir(
            parents=True, exist_ok=True)
        create_page(
            path + f'/{day_number}.html',
            title, day_body_html + next_prev_html, day_archive_html,
            config,
            label, min_year, max_year
        )

        year_week = get_year_week(day['date'])
        if year_week == current_year_week:
            week_body_html += day_body_html
        else:
            create_week_page(
                current_year_week, week_body_html, archive, config,
                min_year, max_year
            )
            current_year_week = year_week
            week_body_html = day_body_html

        index += 1

    create_week_page(
        year_week, week_body_html, archive, config,
        min_year, max_year
    )

def create_json_feed(days, config):
    items = []
    todo = config['days']

    for day in days:
        html = ''
        for entry in day['entries']:
            html += html_for_entry(entry)

        year, month, day_number = split_date(day['date'])
        url = urllib.parse.urljoin(
            config['blog-url'], f'archive/{year}/{month}/{day_number}.html')
        title = day['title']
        if not title:
            title = parse_date(day['date']).strftime(config['date-format'])

        items.append({
            'id':    url,
            'url':   url,
            'title': title,
            'content_html':   html,
            'date_published': day['date']
        })
        todo -= 1
        if not todo:
            break

    feed = {
        'version':       'https://jsonfeed.org/version/1',
        'title':         config['name'],
        'home_page_url': config['blog-url'],
        'feed_url':      config['feed-url'],
        'author': {
            'name': config['author']
        },
        'items': items
    }
    path = config['feed-path']
    p = Path(config['output-dir']).joinpath(path)
    with p.open(mode='w', encoding='utf-8') as f:
        json.dump(feed, f, indent=3, ensure_ascii=False, sort_keys=True,
                  separators=(',', ': '))
        print('', file=f)

    if not config['quiet']:
        print(f"Created '{path}'")

def create_blog(config):
    days = collect_days(read_tumblelog_entries(config['filename']))

    max_year = (split_date(days[0]['date']))[0]
    min_year = (split_date(days[-1]['date']))[0]

    archive = create_archive(days)

    create_index(days, archive, config, min_year, max_year)
    create_day_and_week_pages(days, archive, config, min_year, max_year)

    create_json_feed(days, config)

def create_argument_parser():
    usage = """
  %(prog)s --template-filename TEMPLATE --output-dir HTDOCS
      --author AUTHOR -name BLOGNAME --blog-url URL
      [--days DAYS ] [--css URL] [--date-format DATE] [--quiet] FILE
  %(prog)s --help"""

    parser = argparse.ArgumentParser(usage=usage)
    parser.add_argument('-t', '--template-filename', dest='template-filename',
                        help='filename of template, required',
                        metavar='TEMPLATE', default=None)
    parser.add_argument('-o', '--output-dir', dest='output-dir',
                        help='directory to store HTML files in, required',
                        metavar='HTDOCS', default=None)
    parser.add_argument('-a', '--author', dest='author',
                        help='author of the blog, required',
                        metavar='AUTHOR', default=None)
    parser.add_argument('-n', '--name', dest='name',
                        help='name of the blog, required',
                        metavar='BLOGNAME', default=None)
    parser.add_argument('-b', '--blog-url', dest='blog-url',
                        help='URL of the blog, required',
                        metavar='URL', default=None)
    parser.add_argument('-d', '--days', dest='days',
                        help='number of days to show on the index;'
                        ' default: %(default)s',
                        metavar='DAYS', type=int, default=14)
    parser.add_argument('-c', '--css', dest='css',
                        help='URL of the stylesheet to use;'
                        ' default: %(default)s',
                        metavar='URL', default='styles.css')
    parser.add_argument('--date-format', dest='date-format',
                        help='how to format the date;'
                        " default: '%(default)s'",
                        metavar='FORMAT', default='%d %b %Y')
    parser.add_argument('--label-format', dest='label-format',
                        help='how to format the label;'
                            "default '%(default)s'",
                        metavar='FORMAT', default='week %V, %Y')
    parser.add_argument('-v', '--version', action='store_true', dest='version',
                        help="show version and exit", default=False)
    parser.add_argument('-q', '--quiet', action='store_true', dest='quiet',
                        help="don't show progress", default=False)

    return parser

def get_config():
    parser = create_argument_parser()
    arguments, args = parser.parse_known_args()
    config = vars(arguments)

    if config['version']:
        print(VERSION)
        sys.exit()

    required = {
        'template-filename':
            'Use --template-filename to specify a template',
        'output-dir':
            'Use --output-dir to specify an output directory for HTML files',
        'author':
            'Use --author to specify an author name',
        'name':
            'Use --name to specify a name for the blog and its feed',
        'blog-url':
            'Use --blog-url to specify the URL of the blog itself',
    }
    for name in sorted(required.keys()):
        if config[name] is None:
            parser.error(required[name])

    if not args:
        parser.error('Specify a filename that contains the blog entries')
    if len(args) > 1:
        print('Additional arguments have been skipped', file=sys.stderr)

    config['filename'] = args[0]
    with open(config['template-filename'], encoding='utf-8') as f:
        config['template'] = f.read()

    config['feed-path'] = 'feed.json'
    config['feed-url'] = urllib.parse.urljoin(
        config['blog-url'], config['feed-path'])

    return config

create_blog(get_config())
