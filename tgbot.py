import asyncio
import logging
import config
from aiogram import Bot, Dispatcher, types
from aiogram.utils.markdown import text, bold
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, F
from aiogram import filters
from aiogram.fsm.context import FSMContext 
from aiogram.filters.state import State, StatesGroup
from aiogram.filters import Command
from pathlib import Path
from aiogram.types.input_file import FSInputFile
import soundfile as sf 
from pydub import AudioSegment
from src.voice_assistant import STTModel, TTSModel
import src.actions as acts

import os
from langchain.document_loaders import TextLoader

# used to create the retriever
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings

# used to create the retriever
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings

# used to create the retrieval tool
from langchain.agents import tool

# used to create the memory
from langchain.memory import ConversationBufferMemory

# used to create the agent executor
from langchain.chat_models import ChatOpenAI
from langchain.agents import AgentExecutor

# used to create the prompt template
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

# retriever part
os.environ["OPENAI_API_KEY"] = config.openai_api_key
# This is needed for both the memory and the prompt
memory_key = "history"
loader = TextLoader(Path("data/raw_data/faq.txt"), encoding='utf8')
data = loader.load()
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
texts = text_splitter.split_documents(data)
embeddings = OpenAIEmbeddings()
db = FAISS.from_documents(texts, embeddings)
retriever = db.as_retriever()
@tool
def tool(query):
    "Searches and returns documents regarding the llm powered autonomous agents blog"
    docs = retriever.get_relevant_documents(query)
    return docs

tools = [tool]
memory = ConversationBufferMemory(memory_key=memory_key, return_messages=True)
system_message = SystemMessage(
        content=(
            "Ты помощница Ашана. Старайся отвечать на все поставленные вопросы. "
            "Для этого в первую очередь используй предоставленные данные Ашана."
            "Рассказывай шутки про покупки."
        )
)
prompt = OpenAIFunctionsAgent.create_prompt(
        system_message=system_message,
        extra_prompt_messages=[MessagesPlaceholder(variable_name=memory_key)]
    )
llm = ChatOpenAI(temperature = 0)
agent = OpenAIFunctionsAgent(llm=llm, tools=tools, prompt=prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, memory=memory, verbose=True)

# bot part
token = config.token
bot = Bot(token=token)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
TEL_REGEXP = r'^\+79[\d]{9}$'
tts_model = TTSModel(Path("data/models/model.pt"))
stt_model = STTModel(Path('data/models/vosk-model-small'))


async def answer(message, msg, reply_markup, parse_mode="MarkdownV2"):
    file_wav = Path("data/raw_data/tts_text.wav")
    combined_sounds = AudioSegment.empty()
    for i in range(0, len(msg), 500):
        infile = f"text_{i}.wav"
        tts_model.str_to_file(msg[i:i+500], infile)
        combined_sounds += AudioSegment.from_wav(infile)
        os.remove(infile)
    combined_sounds.export(file_wav, format="wav")
    voice = FSInputFile(file_wav)
    await bot.send_voice(message.from_user.id, voice, caption=msg[:1000], reply_markup=reply_markup)
    if len(msg) >= 1000:
        await message.answer(msg[1000:].replace('.', '\.').replace('-', '\-'), parse_mode=parse_mode, reply_markup=reply_markup)
    os.remove(file_wav)  # Удаление временного файла 


def make_keyboard(menu):
    keyboard = [[types.KeyboardButton(text=menu_point)] for menu_point in menu]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

class UserStates(StatesGroup):
    person = State()
    ask_tel = State()
    tel = State()
    name = State()
    ready = State()
    
@router.message(UserStates.person, lambda message: message.text == "Вызов оператора")
@router.message(UserStates.person, lambda message: message.text == "Мои заказы")
@router.message(UserStates.person,lambda message: message.text == "Регистрация пластиковой карты")
@router.message(UserStates.person,lambda message: message.text == "Регистрация виртуальной карты")
@router.message(UserStates.person,lambda message: message.text == "Получить социальный статус")
@router.message(UserStates.person,lambda message: message.text == "У меня не получилось накопить")
@router.message(UserStates.person,lambda message: message.text == "У меня не получилось потратить")
@router.message(UserStates.person,lambda message: message.text == "Какой у меня баланс")
async def cmd_init(message: types.Message, state: FSMContext):
    await state.set_state(UserStates.ask_tel.state)
    menu_list = ["Главное меню"]
    msg = text("Укажите, пожалуйста, свой номер телефона  в формате +79ХХХХХХХХХ.\n\
Отправляя номер телефона, вы даете согласие на обработку персональных данных.\n\
Подробнее: https://www.auchan.ru/privacy-policy/")
    await answer(message, msg, make_keyboard(menu_list))


@router.message(UserStates.ask_tel, F.text.regexp(TEL_REGEXP))
async def cmd_save_person(message: types.Message, state: FSMContext):
    await state.update_data(telephone=message.text.lower())
    await state.set_state(UserStates.tel.state)
    menu_list = ["Продолжить", "Не согласен"]
    msg = text("Продолжая диалог, вы соглашаетесь с правилами лояльности, а также даете согласие на получение информации об акциях и скидках: https://www\.auchan\.ru/pl/\n\
Если вам не нужна информация о ваших скидках, пожалуйста, отправьте нам текстовое сообщение \"Не согласен\"")
    await answer(message, msg, make_keyboard(menu_list))

@router.message(UserStates.tel, lambda message: message.text == "Продолжить")
@router.message(UserStates.tel, lambda message: message.text == "Не согласен")
async def cmd_ask_name(message: types.Message, state: FSMContext):
    msg = text("Как вас зовут?")
    await state.set_state(UserStates.name.state)
    await answer(message, msg, types.ReplyKeyboardRemove())

@router.message(UserStates.name)
async def cmd_save_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    msg = text("Приятно познакомиться, ", message.text,"🤗")
    await state.set_state(UserStates.ready.state)
    menu_list = ["Карта АШАН", "Мои покупки", "Акции", "Поиск магазина", "Вызов оператора"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(Command("start"))
@router.message(lambda message: message.text == "Главное меню")
async def cmd_main_menu(message: types.Message, state: FSMContext):
    if await state.get_state() != UserStates.ready.state:
        await state.set_state(UserStates.person.state)

    menu_list = ["Карта АШАН", "Мои покупки", "Акции", "Поиск магазина", "Вызов оператора", "Пошути"]
    msg = text("Для продолжения, пожалуйста, выберите категорию запроса, и я с удовольствием вам помогу 🤗")
    await answer(message, msg, make_keyboard(menu_list))


@router.message(lambda message: message.text == "Пошути")
async def cmd_tell_joke(message: types.Message, state: FSMContext):
    menu_list = ["Главное меню"]
    msg = text(acts.tell_joke())
    await answer(message, msg, make_keyboard(menu_list))

@router.message(lambda message: message.text == "Карта АШАН")
async def cmd_card(message: types.Message, state: FSMContext):
    msg = text('💳 Регистрируйте карту АШАН и получайте море преимуществ!\
Возвращаем баллами до 70% от стоимости товаров со специальными ценниками\n\
Оплачивайте до 100% стоимости покупки баллами! И всё по честному курсу: 1 балл = 1 рубль!\
Подробнее: https://www.auchan.ru/karta-auchan/\n\
Что вы хотите узнать? 😉', sep='\n')
    menu_list = ["Какой у меня баланс", "Действия с баллами", "Социальный статус", "Регистрация карты", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))



@router.message(UserStates.ready, lambda message: message.text == "Какой у меня баланс")
async def cmd_get_balance(message: types.Message, state: FSMContext):
    #ПОТЕНЦИАЛЬНО: обращение к бд
    msg = text('💳  Ваша карта активна. Сейчас на вашей карте: \n🟡 0 базовых баллов \n🔴 0 экспресс-баллов \n🎫 0 купонов', sep='\n')
    menu_list = ["Не согласен с суммой на балансе", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(UserStates.ready, lambda message: message.text == "Вызов оператора")
async def cmd_call_op(message: types.Message, state: FSMContext):
    #НУЖНО: обращение к оператору
    menu_list = ["Главное меню"]
    msg = text('Минуту, уже ищу свободного оператора. Пожалуйста, подождите')
    await answer(message, msg, make_keyboard(menu_list))

@router.message(lambda message: message.text == "Не согласен с суммой на балансе")
@router.message(lambda message: message.text == "У меня не получилось накопить")
@router.message(lambda message: message.text == "У меня не получилось потратить")
async def cmd_connect_op(message: types.Message, state: FSMContext):
    #НУЖНО: обращение к оператору
    menu_list = ["Главное меню"]
    msg = text('Мне потребуется подключить оператора. Он поможет решить вопрос')
    await answer(message, msg, make_keyboard(menu_list))
    


@router.message(lambda message: message.text == "Действия с баллами")
async def cmd_points(message: types.Message, state: FSMContext):
    msg = text('Пожалуйста, выберите вопрос, по которому вас проконсультировать:', sep='\n')
    menu_list = ["Как накопить баллы", "Как потратить баллы", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(lambda message: message.text == "Как накопить баллы")
async def cmd_gain_points(message: types.Message, state: FSMContext):
    msg = text('Получайте кешбэк баллами до 70% за покупку товаров со специальными ценниками.\
Для накопления и списания баллов покажите карту на кассе перед оплатой покупки.\n\
А еще дарим праздничный кешбэк 10% за неделю до и после Дня рождения.\n\
Подробнее:  https://www.auchan.ru/personal-settings/loyalty/my-suggestions/darim-bally-na-den-rozhdeniya/', sep='\n')
    menu_list = ["У меня не получилось накопить", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(lambda message: message.text == "Как потратить баллы")
async def cmd_spend_points(message: types.Message, state: FSMContext):
    msg = text('Оплачивайте до 100% стоимости покупок баллами во всех магазинах АШАН.\n\
Для списания баллов перед оплатой отсканируйте карту АШАН.\n\
Обратите внимание, что списывать баллы можно только если карта зарегистрирована.\n\
Баллы не списываются:\n\
- На табак и табачную продукцию;\n\
- На алкогольную продукцию;\n\
- На покупку подарочных карт АШАН;\n\
- На покупку карт лояльности АШАН.', sep='\n')
    menu_list = ["У меня не получилось потратить", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(lambda message: message.text == "Социальный статус")
async def cmd_ss(message: types.Message, state: FSMContext):
    msg = text('По будням с 7:00 до 12:00 начисляем дополнительный кешбэк 7% баллами клиентам с социальным статусом!\n\
Как получать социальный кешбэк?\n\
Зарегистрируйте карту АШАН\n\
Получите социальный статус карты АШАН\n\
Покажите карту сотруднику магазина перед оплатой покупки\n\
Ознакомиться со списком категорий и документов можно здесь https://www.auchan.ru/karta-auchan/pravila-programmy/, пункт 4.2.1.', sep='\n')
    menu_list = ["Получить социальный статус", "Главное меню", "Вызов оператора"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(UserStates.ready, lambda message: message.text == "Получить социальный статус")
async def cmd_get_ss(message: types.Message, state: FSMContext):
    msg = text('Кому предоставляется?\n\
Социальный статус предоставляется покупателям, относящимся к социальным категориям граждан. Информацию о льготах можно найти в Правилах Программы лояльности: https://www.auchan.ru/karta-auchan/pravila-programmy/?punkt=42\n\
Как посмотреть, есть ли у меня социальный статус?\n\
На сайте в личном кабинете по ссылке\
https://www.auchan.ru/personal-settings/my-profile/\n\
Как получить?\n\
Для получения социального статуса необходимо отправить документ, подтверждающий право получения льготы.\
Пришлите фото или скан-копию документа в ответ на это сообщение', sep='\n')
    menu_list = ["Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(lambda message: message.text == "Регистрация карты")
async def cmd_card_reg(message: types.Message, state: FSMContext):
    msg = text('Выберите тип карты', sep='\n')
    menu_list = ["Регистрация пластиковой карты", "Регистрация виртуальной карты", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(UserStates.ready, lambda message: message.text == "Регистрация пластиковой карты")
async def cmd_plastic_card_reg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = text(f'{data["name"]}, пожалуйста, напишите номер вашей карты АШАН', sep='\n')
    menu_list = ["Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(UserStates.ready, lambda message: message.text == "Регистрация виртуальной карты")
async def cmd_virt_card_reg(message: types.Message, state: FSMContext):

    data = await state.get_data()
    msg = text(f'{data["name"]},  для регистрации карты АШАН, пожалуйста, скачайте приложение Мой АШАН по ссылке: https://mobile.auchan.ru/newapp/\
Или просто перейдите в раздел "Карта Ашан" на сайте https://www.auchan.ru/personal-settings/loyalty/my-card/', sep='\n')
    menu_list = ["Вызов оператора", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(lambda message: message.text == "Мои покупки")
async def cmd_purchases(message: types.Message, state: FSMContext):
    msg = text('Пока я могу проконсультировать вас только по интернет-заказам. Информацию о покупках в магазинах АШАН и АТАК можно увидеть в личном кабинете на сайте  https://www.auchan.ru/personal-settings/my-purchases/\n\
Выберите пункт меню', sep='\n')
    menu_list = ["Мои заказы", "Возвраты", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(UserStates.ready, lambda message: message.text == "Мои заказы")
async def cmd_orders(message: types.Message, state: FSMContext):
    #ПОТЕНЦИАЛЬНО: обращение к бд, поиск заказов клиента 
    msg = text('По указанному номеру телефона заказов не найдено', sep='\n')
    menu_list = ["Возвраты", "Главное меню", "Вызов оператора"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(lambda message: message.text == "Возвраты")
async def cmd_returns(message: types.Message, state: FSMContext):
    msg = text('Выберите интересующий вас пункт меню', sep='\n')
    menu_list = ["Условия возврата товара", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))
 
@router.message(lambda message: message.text == "Условия возврата товара")
async def cmd_return_terms(message: types.Message, state: FSMContext):
    msg = text('Вернуть товар — ЛЕГКО!\n\
В магазинах АШАН и АТАК:\n\
При покупке в гипермаркете - обратитесь в любой гипермаркет на Пункт обслуживания клиентов.\n\
Купили товар в супермаркете? Верните в том же магазине. Обратитесь, пожалуйста, к сотруднику касс.\n\
Не забудьте взять с собой чек и банковскую карту, с которой производилась оплата\n\
В интернет-магазине Ашан.ру:\n\
просто вызовите оператора по кнопке здесь или обратитесь на пункт обслуживания клиентов в ближайший гипермаркет АШАН.\n\
Обратите, пожалуйста, внимание, что есть некоторые законодательные ограничения на возврат товаров. Пожалуйста, ознакомьтесь: https://www.auchan.ru/help/service/vozvrat/', sep='\n')
    menu_list = ["Вызов оператора", "Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))
 
@router.message(lambda message: message.text == "Акции")
async def cmd_promotions(message: types.Message, state: FSMContext):
    msg = text('Тысячи товаров для вас по суперценам https://www.auchan.ru/superceny/', sep='\n')
    menu_list = ["Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))

@router.message(lambda message: message.text == "Поиск магазина")
async def cmd_shop_search(message: types.Message, state: FSMContext):
    msg = text('Выберите способ', sep='\n')
    keyboard = [[types.KeyboardButton(text="По геолокации", request_location=True)],
                [types.KeyboardButton(text="Главное меню")]]
    await message.answer(msg, reply_markup=types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True))

@router.message(F.location)
async def cmd_shop_search_by_geo(message: types.Message, state: FSMContext):
    #ПОТЕНЦИАЛЬНО: обращение к бд, поиск ближайшего магазина
    lat = message.location.latitude
    lon = message.location.longitude
    msg = text(f'АШАН около точки ({lon}, {lat}), https://yandex.ru/maps/?ll={lon},{lat}&pt={lon},{lat}&z=12&l=map', sep='\n')
    menu_list = ["Главное меню"]
    await answer(message, msg, make_keyboard(menu_list))


@router.message(UserStates.ask_tel)
async def cmd_check_person(message: types.Message, state: FSMContext):
    menu_list = ["Главное меню"]
    msg = text("Неправильный формат номера. Попробуйте ещё раз")
    await answer(message, msg, make_keyboard(menu_list))

@router.message(F.text)
async def unknown_text_message(message: types.Message, state: FSMContext):
    menu_list = ["Главное меню"]
    msg = text(await use_chain(message.text))
    await answer(message, msg, make_keyboard(menu_list))

@router.message(F.voice)
async def voice_message_handler(message: types.Message, state: FSMContext):
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    file_ogg = Path("data/raw_data/", f"{file_id}.ogg")
    file_wav = Path("data/raw_data/", f"{file_id}.wav")
    await bot.download_file(file_path, destination=file_ogg)
    data, samplerate = sf.read(file_ogg)
    sf.write(file_wav, data, samplerate)
    str_text = stt_model.file_to_str(file_wav)
    os.remove(file_wav)
    os.remove(file_ogg)
    menu_list = ["Главное меню"]
    msg = text(await use_chain(str_text))
    await answer(message, msg, make_keyboard(menu_list))

@router.message()
async def unknown_message(message: types.Message, state: FSMContext):
    menu_list = ["Главное меню"]
    msg = text('Я не знаю, что с этим делать')
    await answer(message, msg, make_keyboard(menu_list))

async def use_chain(text):
    result = agent_executor({"input": text})
    return result["output"]

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())