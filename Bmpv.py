import subprocess, re, json, requests, tempfile, io, threading, logging, argparse, sys
from danmaku2ass import ReadCommentsBilibili, ProcessComments

if sys.version_info < (3, 7):
    raise RuntimeError('At least Python 3.7 is required')
if subprocess.run(['which', 'you-get'],
                  stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL).returncode:
    raise RuntimeError('you-get is required in PATH')
if subprocess.run(['which', 'mpv'],
                  stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL).returncode:
    raise RuntimeError('mpv is required in PATH')


class Bmpv:
    def __init__(self, quality, url):
        self.quality = quality
        self.url = url
        # Init two threads for async tasks
        t_info = threading.Thread(target=self.getInfo)
        t_info.start()
        t_comments = threading.Thread(target=self.getComments)
        t_comments.start()

        # Wait for both to complete
        t_comments.join()
        t_info.join()

        # Process after getting video because height is required
        self.processComments()

    def getInfo(self):
        logging.info('Start getting video info\n')
        try:
            # output = subprocess.check_output(['you-get', '-u', url])[0].decode()
            # return re.findall("(https:.*)\\n", re.findall("Real URLs:\n(.*)", output, re.S)[0])
            self.info = json.loads(
                subprocess.check_output(['you-get', '--json', self.url]))
            # REF https://github.com/Ylin97/Play-by-mpv/blob/main/play_by_mpv.pys
            logging.info(
                f'Available formats: {[_ for _ in self.info["streams"].keys() if "dash" not in _]}'
            )
            logging.info('Done getting video info\n')
        except subprocess.CalledProcessError:
            logging.error('CalledProcessError')

        # Use best quality available if not defined quality
        try:
            self.sources = self.info['streams'][self.quality]['src']
        except KeyError:
            self.sources = list(self.info['streams'].values())[0]['src']
            logging.warning('Default quality unavailable\n')

        # Temporary file as subtitle
        self.subtitle = tempfile.NamedTemporaryFile(suffix='.ass').name
        logging.info(f'Temporary .ass file at: {self.subtitle}')
        self.width, self.height = subprocess.getoutput(
            f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "{self.sources[0]}"'
        ).split('x')
        logging.info(f'Width: {self.width}')
        logging.info(f'Height: {self.height}')

    def getComments(self):
        logging.info('Start getting comments\n')
        initial_state = json.loads(
            re.findall(r'__INITIAL_STATE__=(.*?);\(function\(\)',
                       requests.get(self.url).text)[0])
        if 'videoData' in initial_state:
            cid = initial_state['videoData']['pages'][0]['cid']
        elif 'videoInfo' in initial_state:
            cid = initial_state['videoInfo']['cid']
        elif 'epInfo' in initial_state:
            cid = initial_state['epInfo']['cid']
        # REF https://github.com/soimort/you-get/blob/a47960f6ed7b2a484b6629678b3a6ad8e39497bd/src/you_get/extractors/bilibili.py#L328
        xml_url = f'https://comment.bilibili.com/{cid}.xml'

        self.comments_str = re.sub(
            '[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]', '\ufffd',
            requests.get(xml_url).content.decode('utf-8'))

        logging.info('Done getting comments\n')

    def processComments(self):
        self.comments = list(
            ReadCommentsBilibili(io.StringIO(self.comments_str),
                                 fontsize=int(self.height) // 20))
        self.comments.sort()

        with open(self.subtitle,
                  'w',
                  encoding='utf-8-sig',
                  errors='replace',
                  newline='\r\n') as f:
            ProcessComments(self.comments,
                            f,
                            width=int(self.width),
                            height=int(self.height),
                            bottomReserved=0,
                            fontface='sans-serif',
                            fontsize=int(self.height) // 20,
                            alpha=1,
                            duration_marquee=10,
                            duration_still=5,
                            filters_regex=[],
                            reduced=False,
                            progress_callback=None)

    def play(self):
        subprocess.run([
            'mpv', '--no-ytdl', self.sources[0],
            f'--audio-file={self.sources[-1]}',
            f'--referrer={self.info["extra"]["referer"]}',
            f'--sub-file={self.subtitle}', '--sid=1'
        ])


def next_ep(url):
    try:
        ep_num = int(re.findall(r'ep([0-9]*)', url)[0])
    except IndexError:
        return None
    return re.sub(r'ep([0-9]*)', f'ep{ep_num+1}', url)


def main():
    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.INFO)
    if len(sys.argv) == 1:
        sys.argv.append('--help')
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument(
        'quality',
        metavar='Q',
        help="Quality of the video: ['flv', 'flv720', 'flv480', 'flv360']")
    parser.add_argument('url', metavar='URL', help='Video URL')
    args = parser.parse_args()
    url = re.findall(r'(.*)\?', args.url.replace('\\', ''))[0]
    # Start first episode manually
    bmpv = Bmpv(args.quality, url)
    while url:
        # thread of the current episode
        cur_last = threading.Thread(target=bmpv.play)
        cur_last.start()
        # At the same time, prepare for next episode
        url = next_ep(url)
        bmpv = Bmpv(args.quality, url)
        # Wait for user to quit mpv
        cur_last.join()


if __name__ == '__main__':
    main()
