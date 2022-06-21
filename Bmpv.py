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
        self.bv = re.findall(r'video/(BV[a-zA-Z0-9]*)\/?\\?\??', url)[0]
        self.url = f'https://www.bilibili.com/video/{self.bv}'
        # Init two threads for async tasks
        t_info = threading.Thread(target=self.getInfo)
        t_info.start()
        t_comments = threading.Thread(target=self.getComments)
        t_comments.start()

        # Wait for both to complete
        t_comments.join()
        t_info.join()

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

    def getComments(self):
        logging.info('Start getting comments\n')
        # REF https://www.bilibili.com/read/cv7923601/
        cid = requests.get(
            f'https://api.bilibili.com/x/player/pagelist?bvid={self.bv}&jsonp=jsonp'
        ).json()['data'][0]['cid']
        # REF https://github.com/soimort/you-get/blob/a47960f6ed7b2a484b6629678b3a6ad8e39497bd/src/you_get/extractors/bilibili.py#L328
        xml_url = f'https://comment.bilibili.com/{cid}.xml'

        s = re.sub('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]', '\ufffd',
                   requests.get(xml_url).content.decode('utf-8'))
        self.comments = list(ReadCommentsBilibili(io.StringIO(s), fontsize=50))
        self.comments.sort()
        logging.info('Done getting comments\n')

    def play(self):
        # Use best quality available if not defined quality
        try:
            sources = self.info['streams'][self.quality]['src']
        except KeyError:
            sources = list(self.info['streams'].values())[0]['src']
            logging.warning('Default quality unavailable\n')

        # Temporary file as subtitle
        self.subtitle = tempfile.NamedTemporaryFile(suffix='.ass').name
        logging.info(f'Temporary .ass file at: {self.subtitle}')
        with open(self.subtitle,
                  'w',
                  encoding='utf-8-sig',
                  errors='replace',
                  newline='\r\n') as f:
            ProcessComments(self.comments,
                            f,
                            width=1920,
                            height=1080,
                            bottomReserved=0,
                            fontface='sans-serif',
                            fontsize=50,
                            alpha=1,
                            duration_marquee=10,
                            duration_still=5,
                            filters_regex=[],
                            reduced=False,
                            progress_callback=None)
            subprocess.run([
                'mpv', '--no-ytdl', sources[0], f'--audio-file={sources[-1]}',
                f'--referrer={self.info["extra"]["referer"]}',
                f'--sub-file={self.subtitle}', '--sid=1'
            ])


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
    bmpv = Bmpv(args.quality, args.url)
    bmpv.play()


if __name__ == '__main__':
    main()
