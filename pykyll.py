import mistletoe
import argparse
import json
import jinja2
import os
import re
import subprocess
import glob
import multiprocessing


POST_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")


def parse_preamble(file):
    with open(file, "r") as fp:
        lines = fp.readlines()
    # read the '---' preamble region of the markdown files and after reading
    # those, delete them before passing the markdown content to the mistletoe
    # parser+renderer or the template string for jinja2 to expand
    preamble = 0
    page_cfg = {}
    for i in range(len(lines)):
        line = lines[i].strip()
        if line.startswith("---"):
            preamble = preamble + 1
            if preamble == 1:
                continue
            elif preamble == 2:
                i = i + 1
                break
        if preamble == 1:
            if line.startswith("#"):  # comment
                continue
            kv = line.split(": ", 1)
            key = kv[0]
            val = kv[1]
            if key == "tags":
                val = val.split(" ")
            # NOTE: This is a hack to not include the surrounding quotes
            elif key == "title":
                if len(val) <= 2:
                    continue
                if val[0] == "\"" and val[-1] == "\"":
                    val = val[1:len(val)-1]
                elif val[0] == "'" and val[-1] == "'":
                    val = val[1:len(val)-1]
            elif key == "needmath":
                val = True if val == "true" else False
            page_cfg[key] = val
    # this means a preamble was found and `page_cfg` was parsed successfully,
    # which means we should delete the preamble before passing the rest of the
    # content to the mistletoe/jinja2 for parsing
    if preamble == 2:
        lines = lines[i:]
    lines = ''.join(lines)
    return page_cfg, lines


def relative_url(url, site):
    if url[0] != "/":
        if url.startswith(site["baseurl"]):
            return "/" + url
        else:
            return "/" + site["baseurl"] + "/" + url
    if not url.startswith("/" + site["baseurl"]):
        return "/" + site["baseurl"] + url
    return url


def reverse(arr):
    return arr[::-1]


# TODO!
def escape(text):
    return text


# TODO!
def cgi_escape(text):
    return text


def length(arr):
    return len(arr)


def post_date(filename):
    base = os.path.basename(filename)
    grp = re.search(POST_DATE, base)
    if not grp:
        raise Exception(f"Post {filename} does not have date prefix!")
    return "%s-%s-%s" % (grp.group(1), grp.group(2), grp.group(3))


def post_last_modified(mdfile):
    out = subprocess.check_output("git log -1 --date=format:'%%Y-%%m-%%d' --format='%%ad' %s" % mdfile, shell=True)
    out = out.strip()
    return out.decode("ascii")


def post_url(filename, site, is_post):
    base = os.path.basename(filename)
    base = base.replace("." + site["extension"], ".html")
    url = os.path.join(site["dirs"]["posts"] if is_post else "",
                       base)
    return url


def recent_posts(posts, top):
    if len(posts) <= 0:
        return []
    rev = reverse(posts)
    if len(rev) < top:
        return rev
    return rev[:top]


def get_tmpl(args, text):
    loader = jinja2.FileSystemLoader(os.path.join(args.cfg["dirs"]["main"],
                                                  args.cfg["dirs"]["layouts"]))
    environment = jinja2.Environment(loader=loader)
    environment.filters["relative_url"] = relative_url
    environment.filters["escape"] = escape
    environment.filters["cgi_escape"] = cgi_escape
    environment.filters["length"] = length
    environment.filters["recent_posts"] = recent_posts
    return environment.from_string(text)


def parse_template(tmplfile, args, content, prev_cfg):
    tmp_cfg = prev_cfg.copy()
    del tmp_cfg["layout"]
    page_cfg, lines = parse_preamble(tmplfile)
    page_cfg.update(tmp_cfg)  # child's preamble gets higher priority
    tm = get_tmpl(args, lines)
    content = tm.render(site=args.cfg, content=content, page=page_cfg)
    if "layout" in page_cfg:
        next_file = os.path.join(args.cfg["dirs"]["main"],
                                 args.cfg["dirs"]["layouts"],
                                 page_cfg["layout"] + ".html")
        content = parse_template(next_file, args, content, page_cfg)
    return content


def parse_markdown(mdfile, args, is_post=False, last_modified=None):
    post = {}
    post["url"] = post_url(mdfile, args.cfg, is_post)
    page_cfg, lines = parse_preamble(mdfile)
    post.update(page_cfg)
    print(f"Generating html for {mdfile}...")
    # modified dates should not be overridden by the preamble!
    if is_post:
        post["date"] = post_date(mdfile)
        post["last_modified"] = last_modified
    # convert to html now along with jinja expansion
    content = mistletoe.markdown(lines)
    if "layout" in page_cfg:
        next_file = os.path.join(args.cfg["dirs"]["main"],
                                 args.cfg["dirs"]["layouts"],
                                 page_cfg["layout"] + ".html")
        content = parse_template(next_file, args, content, post)
    # collect all tags mentioned for this post
    if "tags" in post:
        for tag in post["tags"]:
            args.cfg["tags"].add(tag)
    if is_post:
        # maintain a global list of posts
        args.cfg["posts"].append(post)
        # also maintain a tags to posts mapping
        for tag in post["tags"]:
            if tag not in args.cfg["tags_to_posts"]:
                args.cfg["tags_to_posts"][tag] = []
            args.cfg["tags_to_posts"][tag].append(post)
    # write the page
    outfile = post["url"]
    d = os.path.dirname(outfile)
    if d and not os.path.exists(d):
        os.makedirs(d)
    with open(outfile, "w") as fp:
        fp.write(content)
    return


def generate_html(args):
    posts_dir = os.path.join(args.cfg["dirs"]["main"],
                             args.cfg["dirs"]["posts"],
                             "*." + args.cfg["extension"])
    posts = glob.glob(posts_dir)
    print("Getting last modified timestamps for all posts...")
    with multiprocessing.Pool(args.np) as p:
        last_modified = p.map(post_last_modified, posts)
    # generate all the posts first
    for idx, file in enumerate(posts):
        parse_markdown(file, args, True, last_modified[idx])
    # put the tags in an alphabetical order
    args.cfg["tags"] = list(args.cfg["tags"])
    args.cfg["tags"].sort()
    # generate the final set of pages inside 'main' directory next
    main_dir = os.path.join(args.cfg["dirs"]["main"],
                            "*." + args.cfg["extension"])
    for file in glob.glob(main_dir):
        parse_markdown(file, args, False)
    return


def validateargs(args):
    pass


def parseargs():
    desc = "Generate jekyll-like pages but using python"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("-cfg", default="config.json", type=str,
        help="Path to the global config file.")
    parser.add_argument("-np", default=10, type=int,
        help="Number of processes to use to run git queries.")
    parser.add_argument("-port", default=5000, type=int,
        help="Port where to listen for the http server.")
    parser.add_argument("-serve", action="store_true", default=False,
        help="Start a server to serve these generated files. This will NOT"
             " generate the files")
    args = parser.parse_args()
    validateargs(args)
    with open(args.cfg, "r") as fp:
        args.cfg = json.load(fp)
        args.cfg["posts"] = []
        args.cfg["tags"] = set()
        args.cfg["tags_to_posts"] = {}
    return args


def serve(args):
    import flask
    parent = os.path.dirname(os.getcwd())
    app = flask.Flask(__name__, static_url_path='', static_folder=parent)
    app.run(port=args.port)


if __name__ == "__main__":
    args = parseargs()
    if args.serve:
        serve(args)
    else:
        generate_html(args)
