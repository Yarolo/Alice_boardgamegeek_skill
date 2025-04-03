from boardgamegeek import BGGClient

import requests

import xmltodict, json


def findgame_old(boardgame_name):
    api_boardgame_name = ''
    i = 124742
    while boardgame_name.lower() not in [s.lower() for s in api_boardgame_name]:
        response = requests.get(f'https://boardgamegeek.com/xmlapi/boardgame/{i}')
        if response.status_code == 404:
            print('Игра не найдена')
            return

        boardgame_info = xmltodict.parse(response.content)
        boardgame_info_name = boardgame_info["boardgames"]["boardgame"].get("name", {'#text': ''})
        if isinstance(boardgame_info_name, dict):
            api_boardgame_name = [boardgame_info_name["#text"]]
        else:
            api_boardgame_name = [name["#text"] for name in boardgame_info_name]
        i += 1

    with open('findgame.json', 'w') as f:
        json.dump(boardgame_info, f)
    print(f'{boardgame_name} - нашли')


def findgame(game_name):
    bgg = BGGClient()
    game = bgg.game(game_name)
    return game


