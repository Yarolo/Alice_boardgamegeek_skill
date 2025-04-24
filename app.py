import os
from flask import Flask, request, jsonify
import logging
from boardgames_info import findgame, game_base_info
from http_work import skill_image_disconnect, image_to_skill_connect

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

sessionStorage = {}
creature = {}


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
        elif ('кост' in req['request']['command'] or 'куб' in req['request']['command']) and 'брос' in req['request'][
            'command']:
            res['response']['text'] = f'Сколько кубиков хотите кинуть?'
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = True
        elif sessionStorage['boardgames_info']:
            boardgames_dialog(req, res)
        elif sessionStorage['dice_pull']:
            dice_dialog(req, res)


def boardgames_dialog(req, res):
    try:
        boardgames = findgame(req['request']['original_utterance'])
    except ValueError as ve:
        res['response']['text'] = ve
    if isinstance(boardgames, list):
        res['response']['text'] = f'''Нет полного соответствия. Уточните свой запрос об игре. 
        Список частичных соответствий:
        {game_base_info}'''
    else:
        res['response']['text'] = game_base_info(boardgames)
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
                'title': 'Результат бросков кубиков',
                'hide': True
            }
        ]


def dice_dialog(req, res):
    pass


def get_first_name(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.FIO':
            return entity['value'].get('first_name', None)


def get_number(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.NUMBER':
            return entity.get('value', None)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
