import os
from waitress import serve
from flask import Flask, request, jsonify
import logging
from boardgames_info import findgame, game_base_info
from http_work import skill_image_disconnect, image_to_skill_connect
import random
import time
from functools import lru_cache

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessionStorage = {}
GAME_CACHE = {}
MAX_CACHE_SIZE = 100
DICE = {1: '⚀', 2: '⚁', 3: '⚂', 4: '⚃', 5: '⚄', 6: '⚅'}

QUICK_RESPONSES = {
    'привет': lambda name: f'Привет, {name}! Чем могу помочь?',
    'здравствуй': lambda name: f'Здравствуй, {name}! Как я могу помочь?',
    'спасибо': 'Пожалуйста! Обращайтесь ещё!',
    'благодарю': 'Всегда рад помочь!',
    'пока': 'До свидания! Хорошего дня!',
    'что ты умеешь': 'Я могу рассказать о настольных играх, бросить кубики или вытянуть карты. Что вас интересует?'
}


@app.route('/post', methods=['POST'])
def main():
    start_time = time.time()
    response = {
        'session': request.json['session'],
        'version': request.json['version'],
        'response': {
            'end_session': False
        }
    }
    handle_dialog(request.json, response)

    logger.info(f"Request processed in {time.time() - start_time:.3f}s")
    return jsonify(response)


def handle_dialog(req, res):
    user_id = req['session']['user_id']
    command = req['request']['command'].lower()

    if sessionStorage.get('image_id'):
        skill_image_disconnect(sessionStorage['image_id'], 'Волобуев Ярослав')
        sessionStorage.pop('image_id', None)

    for quick_cmd, response in QUICK_RESPONSES.items():
        if quick_cmd in command:
            if callable(response):
                res['response']['text'] = response(sessionStorage.get(user_id, {}).get('first_name', 'друг'))
            else:
                res['response']['text'] = response
            return

    if req['session']['new']:
        res['response']['text'] = 'Привет! Назови свое имя!'
        sessionStorage[user_id] = {'first_name': None}
        return
    if sessionStorage[user_id]['first_name'] is None:
        acquaintance(req, res, user_id)
    else:
        if 'игр' in command and 'настольн' in command:
            res['response']['text'] = 'О какой настольной игре рассказать?'
            sessionStorage['boardgames_info'] = True
            sessionStorage['dice_pull'] = False
            sessionStorage['draw_cards'] = False
        elif ('кост' in command or 'куб' in command) and 'брос' in command:
            res['response']['text'] = 'Сколько кубиков кидаем?'
            sessionStorage['draw_cards'] = False
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = True
        elif ('вытя' in command or 'результат' in command) and 'карт' in command:
            res['response']['text'] = 'Сколько карт вытягиваем?'
            sessionStorage['draw_cards'] = True
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = False
        elif sessionStorage.get('boardgames_info'):
            boardgames_dialog(req, res)
        elif sessionStorage.get('dice_pull'):
            dice_dialog(req, res)
        elif sessionStorage.get('draw_cards'):
            draw_cards(req, res)


def boardgames_dialog(req, res):
    query = req['request']['original_utterance'].lower().strip()

    if query in GAME_CACHE:
        cached = GAME_CACHE[query]
        res['response']['text'] = cached['text']
        if 'image' in cached:
            im_id = image_to_skill_connect(cached['image'], 'Волобуев Ярослав')
            if im_id:
                res['response']['card'] = cached['card']
                sessionStorage['image_id'] = im_id
        return

    try:
        boardgames = findgame(query)
        info = game_base_info(boardgames)
        res['response']['text'] = info

        if not isinstance(boardgames, list):
            if len(GAME_CACHE) >= MAX_CACHE_SIZE:
                GAME_CACHE.pop(next(iter(GAME_CACHE)))

            GAME_CACHE[query] = {
                'text': info,
                'image': boardgames['image'],
                'card': {
                    "type": "BigImage",
                    "image_id": "",
                    "title": boardgames['name'],
                    "description": info,
                }
            }

            im_id = image_to_skill_connect(boardgames['image'], 'Волобуев Ярослав')
            if im_id:
                res['response']['card'] = {
                    "type": "BigImage",
                    "image_id": im_id,
                    "title": boardgames['name'],
                    "description": info,
                }
                sessionStorage['image_id'] = im_id
    except Exception as e:
        logger.error(f"Game search error: {str(e)}")
        res['response']['text'] = 'Извините, не смогла найти информацию об этой игре'


def acquaintance(req, res, user_id):
    first_name = get_first_name(req)
    if first_name is None:
        res['response']['text'] = 'Не расслышала имя. Повтори, пожалуйста!'
    else:
        sessionStorage[user_id]['first_name'] = first_name
        res['response']['text'] = f'Приятно познакомиться, {first_name.title()}! Чем помочь?'
        res['response']['buttons'] = [
            {'title': 'Информация о настольной игре', 'hide': True},
            {'title': 'Бросить кубики', 'hide': True},
            {'title': 'Вытянуть карты', 'hide': True}
        ]


def dice_dialog(req, res):
    num_dice = get_number(req)
    if not num_dice or num_dice < 1:
        res['response']['text'] = 'Пожалуйста, укажите число от 1 до 10'
        return
    num_dice = min(num_dice, 10)
    result = sorted([DICE[random.randint(1, 6)] for _ in range(num_dice)])
    res['response']['text'] = f'Результат: {"".join(result)}'


def draw_cards(req, res):
    CARD_SUITS = {'spades': '♠', 'hearts': '♥', 'diamonds': '♦', 'clubs': '♣'}
    CARD_VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    full_deck = [f"{value}{suit}" for suit in CARD_SUITS.values() for value in CARD_VALUES]

    num_cards = get_number(req)
    if not num_cards or num_cards < 1:
        res['response']['text'] = "Пожалуйста, укажите число от 1 до 10"
        return

    num_cards = min(num_cards, 10)
    drawn_cards = random.sample(full_deck, num_cards)
    res['response']['text'] = f"Вытянутые карты: {' '.join(drawn_cards)}"


def get_first_name(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.FIO':
            return entity['value'].get('first_name', None)


def get_number(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.NUMBER':
            return entity.get('value', None)


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=5000)
