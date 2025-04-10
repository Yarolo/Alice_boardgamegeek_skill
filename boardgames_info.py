from re import search

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
    game_name_cor = game_name.strip()
    games = []
    bgg = BGGClient()
    try:
        game = bgg.game(game_name_cor)
        return game
    except Exception:
        pass
    search_results = bgg.search(game_name_cor)
    for i in search_results:
        try:
            game = bgg.game(game_id=i.id)
            if game.users_commented == 0:
                continue
            if game.name.lower() == game_name_cor:
                return game
            games.append(game)
        except Exception:
            print('not game')
    games = sorted(games, key=lambda x: x.users_commented, reverse=True)
    return [i.name + ' ' + str(i.year) + '\n' for i in games]


def game_base_info(game):
    return game.description


if __name__ == '__main__':
    print(game_base_info(findgame('Monopoly')))
