import os
from flask import Flask, request, jsonify
import logging
from boardgames_info import findgame, game_base_info
from http_work import skill_image_disconnect, image_to_skill_connect, request_repeat
import random

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

sessionStorage = {}

DICE = {1: '⚀', 2: '⚁', 3: '⚂', 4: '⚃', 5: '⚄', 6: '⚅'}


@app.route('/post', methods=['POST'])
def main():
    response = {
        'session': request.json['session'],
        'version': request.json['version'],
        'response': {
            'end_session': False
        }
    }
    handle_dialog(request.json, response)

    return jsonify(response)


def handle_dialog(req, res):
    user_id = req['session']['user_id']
    if sessionStorage.get('image_id'):
        skill_image_disconnect(sessionStorage['image_id'], 'Волобуев Ярослав')

    if req['session']['new']:
        res['response']['text'] = 'Привет! Назови свое имя!'

        sessionStorage[user_id] = {
            'first_name': None
        }
        return
    if sessionStorage[user_id]['first_name'] is None:
        acquaintance(req, res, user_id)
    else:
        if 'игр' in req['request']['command'] and 'настольн' in req['request']['command']:
            res['response']['text'] = f'Супер! Информацию о какой настольной игре хочешь узнать?'
            sessionStorage['boardgames_info'] = True
            sessionStorage['dice_pull'] = False
            sessionStorage['draw_cards'] = False
        elif ('кост' in req['request']['command'] or 'куб' in req['request']['command']) and 'брос' in req['request'][
            'command']:
            res['response']['text'] = f'Сколько кубиков хотите кинуть?'
            sessionStorage['draw_cards'] = False
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = True
        elif ('вытя' in req['request']['command'] or 'результат' in req['request']['command']) and 'карт' in \
                req['request']['command']:
            res['response']['text'] = f'Сколько карт хотите вытянуть?'
            sessionStorage['draw_cards'] = True
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = False
        elif sessionStorage['boardgames_info']:
            boardgames_dialog(req, res)
        elif sessionStorage['dice_pull']:
            dice_dialog(req, res)
        elif sessionStorage['draw_cards']:
            draw_cards(req, res)


def boardgames_dialog(req, res):
    try:
        boardgames = findgame(req['request']['original_utterance'])
    except ValueError:
        res['response']['text'] = 'Извините, не смогла найти игру с таким именем'
        return
    res['response']['text'] = game_base_info(boardgames)
    if not isinstance(boardgames, list):
        im_id = image_to_skill_connect(boardgames['image'], 'Волобуев Ярослав')
        res['response']['card'] = {
            "type": "BigImage",
            "image_id": im_id,
            "title": boardgames['name'],
            "description": game_base_info(boardgames),
        }
        sessionStorage['image_id'] = im_id


def acquaintance(req, res, user_id):
    first_name = get_first_name(req)
    if first_name is None:
        res['response']['text'] = \
            'Не расслышала имя. Повтори, пожалуйста!'
    else:
        sessionStorage[user_id]['first_name'] = first_name
        res['response'][
            'text'] = f'Приятно познакомиться, {first_name.title()}. Что хотите узнать?'
        res['response']['buttons'] = [
            {
                'title': 'Информацию о настольной игре',
                'hide': True
            },
            {
                'title': 'Значение вытянутых карт',
                'hide': True
            },
            {
                'title': 'Результат бросков кубиков',
                'hide': True
            }
        ]


def dice_dialog(req, res):
    number_dices = get_number(req)
    result = []
    if not number_dices:
        res['response']['text'] = 'Не расслышала ответ. Введите число брошенных кубиков.'
        return
    for i in range(number_dices):
        result.append(DICE[random.choice(range(1, 7))])
    result = sorted(result)
    answer = f'Ваш результат:\n{"".join(result)}'
    if number_dices == 5:
        combos = []
        for i in DICE.values():
            combos.append(result.count(i))
        if 5 in combos:
            answer += '\n Комбинация из кубиков: Покер.'
        elif 3 in combos and 2 in combos:
            answer += '\n Комбинация из кубиков: Фулхаус.'
        elif result == '⚀⚁⚂⚃' or result == '⚁⚂⚃⚄' or result == '⚂⚃⚄⚅':
            answer += '\n Комбинация из кубиков: Короткий стрит.'
        elif result == '⚁⚂⚃⚄⚅' or result == '⚀⚁⚂⚃⚄':
            answer += '\n Комбинация из кубиков: Длинный стрит.'
        elif 4 in combos:
            answer += '\n Комбинация из кубиков: Каре.'

    res['response']['text'] = answer


def get_first_name(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.FIO':
            return entity['value'].get('first_name', None)


def get_number(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.NUMBER':
            return entity.get('value', None)


def draw_cards(req, res):
    CARD_SUITS = {
        'spades': '♠',
        'hearts': '♥',
        'diamonds': '♦',
        'clubs': '♣'
    }

    CARD_VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

    full_deck = []
    for suit in CARD_SUITS.values():
        for value in CARD_VALUES:
            full_deck.append(f"{value}{suit}")

    num_cards = get_number(req)

    if not num_cards or num_cards <= 0:
        res['response']['text'] = "Пожалуйста, укажите положительное число карт для выбора."
        return

    if num_cards > len(full_deck):
        res['response']['text'] = f"В колоде только {len(full_deck)} карт. Вы не можете выбрать больше."
        return

    drawn_cards = random.sample(full_deck, num_cards)

    if num_cards == 1:
        res['response']['text'] = f"Выбранная карта: {drawn_cards[0]}"
    else:
        res['response']['text'] = f"Выбранные карты: {' '.join(drawn_cards)}"


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
