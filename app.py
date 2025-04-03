import os
from flask import Flask, request, jsonify
import logging
from boardgames_info import findgame

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

sessionStorage = {}
creature = {}


@app.route('/post', methods=['POST'])
def main():
    logging.info(f'Request: {request.json!r}')

    response = {
        'session': request.json['session'],
        'version': request.json['version'],
        'response': {
            'end_session': False
        }
    }

    handle_dialog(request.json, response)

    logging.info(f'Response:  {response!r}')

    return jsonify(response)


def handle_dialog(req, res):
    user_id = req['session']['user_id']

    if req['session']['new']:
        res['response']['text'] = 'Привет! Назови свое имя!'

        sessionStorage[user_id] = {
            'first_name': None
        }
        return

    if sessionStorage[user_id]['first_name'] is None:
        first_name = get_first_name(req)
        if first_name is None:
            res['response']['text'] = \
                'Не расслышала имя. Повтори, пожалуйста!'
        else:
            sessionStorage[user_id]['first_name'] = first_name
            res['response'][
                'text'] = 'Приятно познакомиться. Рейтинг какой настольной игры хочешь узнать?'
        print(f'Игра имеет рейтинг {findgame(req['request']['command']).rating_average_weight} из 10')
        return


def get_first_name(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.FIO':
            return entity['value'].get('first_name', None)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
