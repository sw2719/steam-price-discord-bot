import sys
import asyncio
import re
import json
import os
import logging
import traceback
import aiohttp
from collections import OrderedDict
from discord.ext import commands
from discord import Embed, Activity, ActivityType
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.WARNING)

print('Python version:', sys.version)

if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):  # 파이썬 3.8 이상 & Windows 환경에서 실행하는 경우
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def reset_cfg():
    default = {"bot_token": "",
               "owner_user_id": "",
               "test_mode": False,
               "interval": 60}

    with open('config.json', 'w') as f:
        f.write(json.dumps(default, indent=4))

    print('Created new config file. Please provide bot token in it.')
    sys.exit()


if not os.path.isfile('config.json'):
    reset_cfg()
else:
    try:
        with open('config.json', 'r') as f:
            cfg = json.loads(f.read())
            TOKEN = cfg['bot_token']
            OWNER_USER_ID = int(cfg['owner_user_id'])
            TEST_MODE = cfg['test_mode']
            INTERVAL = cfg['interval']
            print('Loaded config file.')
            print('Test mode:', TEST_MODE)
            print('Interval:', INTERVAL)

        del cfg

    except KeyError:
        reset_cfg()


class SteamPriceBot(commands.Bot):
    def __init__(self):
        super().__init__('.')
        self.item_dict = OrderedDict()

        try:
            with open('added_products.json', 'r') as f:
                self.id_dict = json.loads(f.read(), object_pairs_hook=OrderedDict)

            for app_id in self.id_dict.keys():
                self.item_dict[str(app_id)] = {}

        except FileNotFoundError:
            print('added_products.json not found. Creating one!')
            with open('added_products.json', 'w') as f:
                f.write(json.dumps({}, indent=4))
            self.id_dict = OrderedDict()

        self.remove_command('help')
        self.add_bot_commands()
        self.bg_task = self.loop.create_task(self.check_price())

    def save_id_dict(self):
        with open('added_products.json', 'w') as f:
            f.write(json.dumps(self.id_dict, indent=4))

    def parse_url(self, input_url):
        if re.match('https://store.steampowered.com/app/[0-9]+', input_url):
            app_id = re.findall('app/([0-9]+)', str(input_url))[0]
            url_type = 'app'

        elif re.match('https://store.steampowered.com/sub/[0-9]+', input_url):
            app_id = re.findall()('sub/([0-9]+)', str(input_url))[0]
            url_type = 'sub'

        elif re.match('https://store.steampowered.com/bundle/[0-9]+', input_url):
            app_id = re.findall('bundle/([0-9]+)', str(input_url))[0]
            url_type = 'bundle'

        else:
            return None, None

        return app_id, url_type

    def add_bot_commands(self):
        @self.command(name='help')
        async def help_(ctx):
            await ctx.message.delete()
            help_msg = Embed(title='명령어 도움말',
                             description='.add [상점 URL]  -  해당 제품을 추가합니다.\n.search [제품 이름]  -  해당 이름으로 검색하여 제품을 추가합니다.\n.remove  -  자신이 추가한 제품을 제거합니다.\n.list  -  추가된 제품 목록을 확인합니다.\n\n<소유자 전용>\n.removeall  -  모든 사용자의 제품을 제거합니다.\n.listall  -  모든 사용자가 추가한 제품을 확인합니다.')
            await ctx.channel.send(embed=help_msg, delete_after=30.0)

        @self.command()
        async def add(ctx, input_url=None):
            if input_url is None:
                def check(message):
                    return message.author.id == ctx.author.id

                add_msg = None

                try:
                    msg = Embed(title='제품 추가',
                                description="추가할 제품의 상점 URL을 입력하세요.\n취소하려면'취소' 라고 입력하세요.")
                    add_msg = await ctx.channel.send(embed=msg)
                    message = await self.wait_for('message', timeout=20.0, check=check)

                except asyncio.TimeoutError:
                    await ctx.message.delete()
                    msg = Embed(title='제품 추가',
                                description='시간이 초과되었습니다. 다시 시도하세요.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return

                if message.content == '취소':
                    await ctx.message.delete()
                    await message.delete()
                    msg = Embed(title='제품 추가',
                                description='추가를 취소했습니다.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return
                else:
                    input_url = message.content
                    await message.delete()
                    await add_msg.delete()

            app_id, url_type = self.parse_url(input_url)

            if not app_id:
                await ctx.message.delete()
                msg = Embed(title='제품 추가 오류',
                            description='올바른 Steam 상점 URL이 아닙니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)
                return

            async with aiohttp.ClientSession() as session:
                result = await self.fetch_steam(session, app_id, url_type, return_value=True)

            if result:
                await ctx.message.delete()
                name, price = result
            else:
                await ctx.message.delete()
                msg = Embed(title='제품 추가 오류',
                            description='오류: 올바르지 않은 URL이거나 현재 판매하지 않는 제품입니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)
                return

            if app_id not in self.id_dict:
                self.id_dict[app_id] = {'user_id': ctx.author.id,
                                        'guild': ctx.guild.id,
                                        'channel': ctx.channel.id,
                                        'type': url_type}
                self.item_dict[app_id] = {}
                self.save_id_dict()

                msg = Embed(title='제품 추가됨',
                            description=f'[{name}]({input_url})이(가) 추가되었습니다.\n현재 가격: {price}')
                await ctx.channel.send(embed=msg, delete_after=15.0)
            else:
                msg = Embed(title='알림',
                            description='이미 추가된 제품입니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)

            return

        @self.command()
        async def search(ctx, *query):

            def check(message):
                return message.author.id == ctx.author.id

            if not query:
                add_msg = None

                try:
                    msg = Embed(title='이름으로 제품 추가',
                                description='추가할 제품의 이름을 입력하세요.')
                    add_msg = await ctx.channel.send(embed=msg)
                    message = await self.wait_for('message', timeout=20.0, check=check)

                except asyncio.TimeoutError:
                    await ctx.message.delete()
                    msg = Embed(title='이름으로 제품 추가',
                                description='시간이 초과되었습니다. 다시 시도하세요.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return

                if message.content == '취소':
                    await ctx.message.delete()
                    await message.delete()
                    msg = Embed(title='이름으로 제품 추가',
                                description='추가를 취소했습니다.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return
                else:
                    query = message.content.split(' ')
                    await message.delete()
                    await add_msg.delete()

            await ctx.message.delete()

            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://store.steampowered.com/search/?term={" ".join(query)}') as r:
                    soup = BeautifulSoup(await r.read(), 'html.parser')

            names = [str(re.sub('<[^<>]*>', '', str(name))) for name in soup.select('div.responsive_search_name_combined > div.col.search_name.ellipsis > span')]
            urls = [str(url['href']) for url in soup.select('#search_resultsRows > a')]
            prices = [str(re.sub('<[^<>]*>', '', str(price))).strip() for price in soup.find_all('div', class_='col search_price responsive_secondrow')]

            for i, price in enumerate(prices):
                if not price:
                    prices[i] = '가격 없음'

            if len(names) > 10:
                max_index = 10
            else:
                max_index = len(names)

            embed_desc = [f"추가할 제품의 번호를 입력하세요. [1-{str(max_index)}]\n취소하려면 '취소'라고 입력하세요.\n"]

            for i, name in enumerate(names):
                if i < 10:
                    embed_desc.append(f'{str(i + 1)}. {name} - {prices[i]}')
                else:
                    break

            add_msg = None

            def check_index(message):
                try:
                    if 1 <= int(message.content) <= max_index:
                        return message.author.id == ctx.author.id

                except ValueError:
                    if message.content == '취소':
                        return message.author.id == ctx.author.id
                    else:
                        pass

            try:
                msg = Embed(title='제품 선택',
                            description='\n'.join(embed_desc))
                add_msg = await ctx.channel.send(embed=msg)
                message = await self.wait_for('message', timeout=20.0, check=check_index)

            except asyncio.TimeoutError:
                msg = Embed(title='제품 선택',
                            description='시간이 초과되었습니다. 다시 시도하세요.')
                await add_msg.edit(embed=msg, delete_after=5.0)
                return

            if message.content == '취소':
                await message.delete()
                msg = Embed(title='제품 선택',
                            description='추가를 취소했습니다.')
                await add_msg.edit(embed=msg, delete_after=5.0)
                return

            else:
                index = int(message.content) - 1
                await message.delete()

            name = names[index]
            price = prices[index]
            app_url = urls[index]
            app_id, url_type = self.parse_url(app_url)

            if app_id not in self.id_dict:
                self.id_dict[app_id] = {'user_id': ctx.author.id,
                                        'guild': ctx.guild.id,
                                        'channel': ctx.channel.id,
                                        'type': url_type}
                self.item_dict[app_id] = {}
                self.save_id_dict()

                msg = Embed(title='제품 추가됨',
                            description=f'[{name}]({app_url})이(가) 추가되었습니다.\n현재 가격: {price}')

                await add_msg.edit(embed=msg, delete_after=15.0)

            else:
                msg = Embed(title='알림',
                            description='이미 추가된 제품입니다.')
                await add_msg.edit(embed=msg, delete_after=10.0)

            return

        @self.command()
        async def remove(ctx):
            if not self.id_dict:
                await ctx.message.delete()
                await ctx.channel.send('추가된 제품이 없습니다.', delete_after=10.0)
                return

            await self.update_dict()

            message_to_send = ["제거할 제품의 번호를 입력하세요. (예시: 1)\n여러 제품을 제거하려면 다음과 같이 입력하세요: '1/2/3'\n취소하려면 '취소'라고 입력하세요.\n"]
            remove_list = []
            index = 0

            for key, value in self.item_dict.items():
                if self.id_dict[key]['user_id'] == ctx.author.id:
                    message_to_send.append(f"{str(index + 1)}: {value['name']}")
                    remove_list.append(key)
                    index += 1

            prompt = await ctx.channel.send('\n'.join(message_to_send))

            def check(message):
                try:
                    if message.content == '취소':
                        return True

                    elif len(message.content.split('/')) > 1 and message.author.id == ctx.author.id:
                        for number in message.content.split('/'):
                            if not 1 <= int(number) <= len(self.id_dict):
                                raise ValueError
                        return True

                    else:
                        return message.author.id == ctx.author.id and 1 <= int(message.content) <= len(self.id_dict)
                except ValueError:
                    pass

            try:
                message = await self.wait_for('message', timeout=20.0, check=check)
            except asyncio.TimeoutError:
                await ctx.message.delete()
                await prompt.delete()
                await ctx.channel.send('시간이 초과되었습니다. 다시 시도하세요.', delete_after=5.0)
                return

            if message.content == '취소':
                await ctx.message.delete()
                await prompt.delete()
                await ctx.channel.send('제거를 취소했습니다.', delete_after=5.0)
                return

            if len(message.content.split('/')) > 1:
                await ctx.message.delete()
                await prompt.delete()
                await message.delete()
                deleted_games = []

                for number in message.content.split('/'):
                    remove_index = int(number) - 1
                    remove_url = remove_list[remove_index]
                    removed_item = self.item_dict[remove_url]['name']

                    del self.item_dict[remove_url]
                    del self.id_dict[remove_url]
                    deleted_games.append(removed_item)

                msg = Embed(title='다음 제품 제거됨',
                            description='\n'.join(deleted_games))

                await ctx.send(embed=msg, delete_after=15.0)

            else:
                await ctx.message.delete()
                await prompt.delete()
                await message.delete()
                remove_index = int(message.content) - 1
                remove_url = remove_list[remove_index]
                removed_item = self.item_dict[remove_url]['name']

                del self.item_dict[remove_url]
                del self.id_dict[remove_url]

                msg = Embed(title='제품 제거됨',
                            description=f'{removed_item}을(를) 제거했습니다.')

                await ctx.send(embed=msg, delete_after=15.0)

            self.save_id_dict()
            return

        @self.command()
        async def removeall(ctx):
            if ctx.author != self.owner:
                await ctx.message.delete()
                await ctx.channel.send('알림: 소유자만 이 명령어를 사용할 수 있습니다.')
                return

            if not self.id_dict:
                await ctx.message.delete()
                await ctx.channel.send('추가된 제품이 없습니다.')
                return

            await self.update_dict()

            message_to_send = ["제거할 제품의 번호를 입력하세요. (예시: 1)\n여러 제품을 제거하려면 다음과 같이 입력하세요: '1/2/3'\n취소하려면 '취소'라고 입력하세요.\n"]
            remove_list = []
            index = 0

            for key, value in self.item_dict.items():
                message_to_send.append(f"{str(index + 1)}: {value['name']}")
                remove_list.append(key)
                index += 1

            prompt = await ctx.channel.send('\n'.join(message_to_send))

            def check(message):
                try:
                    if message.content == '취소':
                        return True

                    elif len(message.content.split('/')) > 1 and message.author.id == ctx.author.id:
                        for number in message.content.split('/'):
                            if not 1 <= int(number) <= len(self.id_dict):
                                raise ValueError
                        return True

                    else:
                        return message.author.id == ctx.author.id and 1 <= int(message.content) <= len(self.id_dict)
                except ValueError:
                    pass

            try:
                message = await self.wait_for('message', timeout=20.0, check=check)
            except asyncio.TimeoutError:
                await ctx.message.delete()
                await prompt.delete()
                await ctx.channel.send('시간이 초과되었습니다. 다시 시도하세요.', delete_after=5.0)
                return

            if message.content == '취소':
                await ctx.message.delete()
                await prompt.delete()
                await ctx.channel.send('제거를 취소했습니다.', delete_after=5.0)
                return

            if len(message.content.split('/')) > 1:
                await ctx.message.delete()
                await prompt.delete()
                await message.delete()
                deleted_games = []

                for number in message.content.split('/'):
                    remove_index = int(number) - 1
                    remove_url = remove_list[remove_index]
                    removed_item = self.item_dict[remove_url]['name']

                    del self.item_dict[remove_url]
                    del self.id_dict[remove_url]
                    deleted_games.append(removed_item)

                msg = Embed(title='다음 제품 제거됨',
                            description='\n'.join(deleted_games))

                await ctx.send(embed=msg, delete_after=15.0)

            else:
                await ctx.message.delete()
                await prompt.delete()
                await message.delete()
                remove_index = int(message.content) - 1
                remove_url = remove_list[remove_index]
                removed_item = self.item_dict[remove_url]['name']

                del self.item_dict[remove_url]
                del self.id_dict[remove_url]

                msg = Embed(title='제품 제거됨',
                            description=f'{removed_item}을(를) 제거했습니다.')

                await ctx.send(embed=msg, delete_after=15.0)

            self.save_id_dict()
            return

        @self.command(name='list')
        async def list_(ctx):
            author = await self.fetch_user(ctx.author.id)
            game_list = []

            for key, value in self.id_dict.items():
                if value['user_id'] == ctx.author.id and ctx.guild == self.get_guild(value['guild']):
                    game_list.append(key)

            if game_list:
                await self.update_dict()
                content = []

                for key, value in self.item_dict.items():
                    if self.id_dict[key]['user_id'] == ctx.author.id and self.get_guild(self.id_dict[key]['guild']) == ctx.guild:
                        if value['on_sale']:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]} ({value["discount_perc"]}% 할인)')
                        else:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]}')

                await ctx.message.delete()
                msg = Embed(title=f'{str(author).split("#")[0]}님은 현재 {str(len(game_list))} 개의 제품이 추가되어 있습니다.',
                            description='\n'.join(content))

                await ctx.channel.send(embed=msg, delete_after=30.0)

            else:
                await ctx.message.delete()
                msg = Embed(title='알림',
                            description=f'{str(author).split("#")[0]}님은 추가하신 제품이 없습니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)

        @self.command(name='listall')
        async def listall(ctx):
            if ctx.author != self.owner:
                await ctx.message.delete()
                await ctx.channel.send('알림: 소유자만 이 명령어를 사용할 수 있습니다.', delete_after=5.0)
                return

            if self.id_dict:
                await self.update_dict()
                content = []

                for key, value in self.item_dict.items():
                    if self.get_channel(self.id_dict[key]['guild']) == ctx.guild:
                        if value['on_sale']:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]} ({value["discount_perc"]}% 할인)')
                        else:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]}')

                await ctx.message.delete()
                msg = Embed(title=f'현재 채널에 {str(len(self.id_dict))} 개의 제품이 추가되어 있습니다.',
                            description='\n'.join(content))

                await ctx.channel.send(embed=msg, delete_after=30.0)

            else:
                await ctx.message.delete()
                msg = Embed(title='알림',
                            description='추가된 제품이 없습니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)

    async def update_dict(self):
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(*[self.fetch_steam(session, key, value['type']) for key, value in self.id_dict.items()])

    async def fetch_bundle(self, session, app_id):
        async with session.get(f'https://store.steampowered.com/bundle/{app_id}') as r:
            session_id = r.cookies.get('sessionid').value

        await session.post(f'https://store.steampowered.com/agecheckset/bundle/{app_id}/', data={'sessionid': session_id, 'ageDay': '1', 'ageMonth': 'January', 'ageYear': '1990'})

        async with session.get(f'https://store.steampowered.com/bundle/{app_id}#') as r:
            content = await r.read()

        soup = BeautifulSoup(content, 'html.parser')
        name = str(re.sub('<[^<>]*>', '', str(soup.find('h2', class_='pageheader'))))
        discount_perc = str(re.sub('<[^<>0-9]*>', '', str(soup.find('div', class_='discount_pct'))))
        initial_formatted = str(re.sub('<[^<>]*>', '', str(soup.find('div', class_='discount_original_price'))))
        final_formatted = str(re.sub('<[^<>]*>', '', str(soup.find('div', class_='discount_final_price'))))

        if discount_perc == 'None':
            on_sale = False
            discount_perc = ''
        else:
            on_sale = True

        initial = re.sub('[^0-9]', '', initial_formatted)
        final = re.sub('[^0-9]', '', final_formatted)

        return name, initial, initial_formatted, final, final_formatted, on_sale, discount_perc

    async def fetch_steam(self, session, app_id, url_type, return_value=False):
        try:
            if url_type == 'bundle':
                name, initial, initial_formatted, final, final_formatted, on_sale, discount_perc = await self.fetch_bundle(session, app_id)

            else:
                if url_type == 'sub':
                    url_type = 'package'

                url = f'https://store.steampowered.com/api/{url_type}details?{url_type}ids={app_id}'

                async with session.get(url) as r:
                    content = await r.read()

                data = json.loads(content)[app_id]['data']
                name = data['name']

                if url_type == 'app':
                    initial = str(data['price_overview']['initial'])[:-2]
                    final = str(data['price_overview']['final'])[:-2]

                    initial_formatted = data['price_overview']['initial_formatted']
                    final_formatted = data['price_overview']['final_formatted']
                    discount_perc = data['price_overview']['discount_percent']

                elif url_type == 'package':
                    initial = str(data['price']['initial'])[:-2]
                    final = str(data['price']['final'])[:-2]

                    initial_formatted = f'₩ {format(int(initial), ",d")}'
                    final_formatted = f'₩ {format(int(final), ",d")}'
                    discount_perc = data['price']['discount_percent']

                else:
                    return

                if discount_perc:
                    on_sale = True
                else:
                    on_sale = False

        except Exception as e:
            print(traceback.format_exc(e))

            if return_value:
                return False
            else:
                await self.owner.send(f'다음 제품을 불러오는 도중 오류가 발생했습니다: {app_id}\n{e}')
                return

        if return_value:
            return name, final_formatted

        else:
            self.item_dict[app_id]['name'] = name
            self.item_dict[app_id]['initial'] = initial
            self.item_dict[app_id]['initial_formatted'] = initial_formatted
            self.item_dict[app_id]['final'] = final
            self.item_dict[app_id]['final_formatted'] = final_formatted
            self.item_dict[app_id]['on_sale'] = on_sale
            self.item_dict[app_id]['discount_perc'] = discount_perc

    async def on_ready(self):
        print(f'Logged in as {self.user.name} | {self.user.id}')
        self.owner_id = OWNER_USER_ID
        self.owner = self.get_user(self.owner_id)
        await self.change_presence(activity=Activity(type=ActivityType.watching, name=".help | Steam"))
        await self.update_dict()

    async def check_price(self):
        await asyncio.sleep(5)

        while not self.is_closed():
            print('Starting price check...')
            try:
                last_dict = self.item_dict
                await self.update_dict()

                for key, value in self.item_dict.items():
                    try:
                        if value['final'] != last_dict[key]['final']:
                            store_url = ''

                            if self.id_dict[key]['type'] == 'app':
                                store_url = f'https://store.steampowered.com/app/{key}'

                            elif self.id_dict[key]['type'] == 'package':
                                store_url = f'https://store.steampowered.com/sub/{key}'

                            elif self.id_dict[key]['type'] == 'bundle':
                                store_url = f'https://store.steampowered.com/bundle/{key}'

                            if value['on_sale']:
                                msg = Embed(title=value['name'],
                                            url=store_url,
                                            description=f'{value["name"]}이(가) 할인 중입니다! \n\n{last_dict[key]["final_formatted"]} -> {value["final_formatted"]} (-{value["discount_perc"]}%')
                            else:
                                msg = Embed(title=value['name'],
                                            url=store_url,
                                            description=f'{value["name"]}의 가격이 변경되었습니다. \n\n{last_dict[key]["final_formatted"]} -> {value["final_formatted"]}')

                            if value['on_sale']:
                                await self.get_channel(self.id_dict[key]['channel']).send(f'<@{self.id_dict[key]["user_id"]}>', embed=msg)
                            else:
                                await self.get_channel(self.id_dict[key]['channel']).send(f'<@{self.id_dict[key]["user_id"]}>', embed=msg)

                    except KeyError:
                        print(traceback.format_exc())
                        pass

                print('Price check ended successfully.')
                await asyncio.sleep(INTERVAL)

            except Exception as e:
                print(f'Price check failed with exception {e}')
                await asyncio.sleep(5)


bot = SteamPriceBot()
bot.run(TOKEN)
