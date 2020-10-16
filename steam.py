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
            with open('added_games.json', 'r') as f:
                self.id_dict = json.loads(f.read(), object_pairs_hook=OrderedDict)

            for app_id in self.id_dict.keys():
                self.item_dict[str(app_id)] = {}

        except FileNotFoundError:
            print('added_games.json not found. Creating one!')
            with open('added_games.json', 'w') as f:
                f.write(json.dumps({}, indent=4))
            self.id_dict = OrderedDict()

        self.remove_command('help')
        self.add_bot_commands()
        self.bg_task = self.loop.create_task(self.check_price())

    def save_id_dict(self):
        with open('added_games.json', 'w') as f:
            f.write(json.dumps(self.id_dict, indent=4))

    def add_bot_commands(self):
        @self.command(name='help')
        async def help_(ctx):
            await ctx.message.delete()
            help_msg = Embed(title='명령어 도움말',
                             description='.add [상점 URL]  -  해당 게임을 추가합니다.\n.remove  -  자신이 추가한 게임을 제거합니다.\n.list  -  추가된 게임 목록을 확인합니다.\n\n<소유자 전용>\n.removeall  -  모든 사용자의 게임을 제거합니다.\n.listall  -  모든 사용자가 추가한 게임을 확인합니다.')
            await ctx.channel.send(embed=help_msg, delete_after=30.0)

        @self.command()
        async def add(ctx, input_url=None):
            if input_url is None:
                def check(message):
                    return message.author.id == ctx.author.id

                add_msg = None

                try:
                    msg = Embed(title='게임 추가',
                                description='추가할 게임의 상점 URL을 입력하세요.\n현재 꾸러미는 지원하지 않습니다.')
                    add_msg = await ctx.channel.send(embed=msg)
                    message = await self.wait_for('message', timeout=20.0, check=check)

                except asyncio.TimeoutError:
                    await ctx.message.delete()
                    msg = Embed(title='게임 추가',
                                description='시간이 초과되었습니다. 다시 시도하세요.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return

                if message.content == '취소':
                    await ctx.message.delete()
                    await message.delete()
                    msg = Embed(title='게임 추가',
                                description='추가를 취소했습니다.')
                    await add_msg.edit(embed=msg, delete_after=5.0)
                    return
                else:
                    input_url = message.content
                    await message.delete()
                    await add_msg.delete()

            if re.match('https://store.steampowered.com/app/[0-9]+', input_url):
                app_id = re.findall('app/([0-9]+)', str(input_url))[0]
                url_type = 'app'

            elif re.match('https://store.steampowered.com/sub/[0-9]+', input_url):
                app_id = re.findall('sub/([0-9]+)', str(input_url))[0]
                url_type = 'sub'

            elif re.match('https://store.steampowered.com/bundle/[0-9]+', input_url):
                await ctx.message.delete()
                msg = Embed(title='게임 추가 오류',
                            description='꾸러미는 지원되지 않습니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)
                return

            else:
                await ctx.message.delete()
                msg = Embed(title='게임 추가 오류',
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
                msg = Embed(title='게임 추가 오류',
                            description='오류: 올바르지 않은 URL이거나 현재 판매하지 않는 게임입니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)
                return

            if app_id not in self.id_dict:
                self.id_dict[app_id] = {'user_id': ctx.author.id,
                                        'channel': ctx.channel.id,
                                        'type': url_type}
                self.item_dict[app_id] = {}
                self.save_id_dict()

                msg = Embed(title='게임 추가됨',
                            description=f'[{name}]({input_url})이(가) 추가되었습니다.\n현재 가격: {price}')
                await ctx.channel.send(embed=msg, delete_after=15.0)
            else:
                msg = Embed(title='알림',
                            description='이미 추가된 게임입니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)

            return

        @self.command()
        async def remove(ctx):
            if not self.id_dict:
                await ctx.message.delete()
                await ctx.channel.send('추가된 게임이 없습니다.', delete_after=10.0)
                return

            await self.update_dict()

            message_to_send = ["제거할 게임의 번호를 입력하세요. (예시: 1)\n여러 게임을 제거하려면 다음과 같이 입력하세요: '1/2/3'\n취소하려면 '취소'라고 입력하세요.\n"]
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

                msg = Embed(title='다음 게임 제거됨',
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

                msg = Embed(title='게임 제거됨',
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
                await ctx.channel.send('추가된 게임이 없습니다.')
                return

            await self.update_dict()

            message_to_send = ["제거할 게임의 번호를 입력하세요. (예시: 1)\n여러 게임을 제거하려면 다음과 같이 입력하세요: '1/2/3'\n취소하려면 '취소'라고 입력하세요.\n"]
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

                msg = Embed(title='다음 게임 제거됨',
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

                msg = Embed(title='게임 제거됨',
                            description=f'{removed_item}을(를) 제거했습니다.')

                await ctx.send(embed=msg, delete_after=15.0)

            self.save_id_dict()
            return

        @self.command(name='list')
        async def list_(ctx):
            author = await self.fetch_user(ctx.author.id)
            game_list = []

            for key, value in self.id_dict.items():
                if value['user_id'] == ctx.author.id and ctx.channel == self.get_channel(value['channel']):
                    game_list.append(key)

            if game_list:
                await self.update_dict()
                content = []

                for key, value in self.item_dict.items():
                    if self.id_dict[key]['user_id'] == ctx.author.id and self.get_channel(self.id_dict[key]['channel']) == ctx.channel:
                        if value['on_sale']:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]} ({value["discount_perc"]}% 할인)')
                        else:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]}')

                await ctx.message.delete()
                msg = Embed(title=f'{str(author).split("#")[0]}님은 현재 {str(len(game_list))} 개의 게임이 추가되어 있습니다.',
                            description='\n'.join(content))

                await ctx.channel.send(embed=msg, delete_after=30.0)

            else:
                await ctx.message.delete()
                msg = Embed(title='알림',
                            description=f'{str(author).split("#")[0]}님은 추가하신 게임이 없습니다.')
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
                    if self.get_channel(self.id_dict[key]['channel']) == ctx.channel:
                        if value['on_sale']:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]} ({value["discount_perc"]}% 할인)')
                        else:
                            content.append(f'[{value["name"]}](https://store.steampowered.com/{self.id_dict[key]["type"]}/{key}) - {value["final_formatted"]}')

                await ctx.message.delete()
                msg = Embed(title=f'현재 채널에 {str(len(self.id_dict))} 개의 게임이 추가되어 있습니다.',
                            description='\n'.join(content))

                await ctx.channel.send(embed=msg, delete_after=30.0)

            else:
                await ctx.message.delete()
                msg = Embed(title='알림',
                            description='추가된 게임이 없습니다.')
                await ctx.channel.send(embed=msg, delete_after=10.0)

    async def update_dict(self):
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(*[self.fetch_steam(session, key, value['type']) for key, value in self.id_dict.items()])

    async def search(self, *query):
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://store.steampowered.com/search/?term={" ".join(query)}') as r:
                content = await r.read()

    async def fetch_steam(self, session, app_id, url_type, return_value=False):
        try:
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

        except Exception as e:
            print(traceback.format_exc())
            if return_value:
                return False
            else:
                await self.owner.send(f'다음 게임을 불러오는 도중 오류가 발생했습니다: {app_id}\n{e}')

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

                            if value['on_sale']:
                                msg = Embed(title=value['name'],
                                            url=store_url,
                                            description=f'{value["name"]}이(가) 할인 중입니다! \n\n{last_dict[key]["final_formatted"]} -> {value["final_formatted"]} (-{value["discount_perc"]}%')
                            else:
                                msg = Embed(title=value['name'],
                                            url=store_url,
                                            description=f'{value["name"]}의 가격이 변경되었습니다: \n\n{last_dict[key]["final_formatted"]} -> {value["final_formatted"]}')

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
