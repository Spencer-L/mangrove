from threading import Lock
from typing import Generator, Dict
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from .persona.protector_of_mangrove import ProtectorOfMangrove

class BotController:
    def __init__(self, assistant_name='Marvin'):
        self.persona = ProtectorOfMangrove(assistant_name=assistant_name)
        self.conversational_qa_chain = self.persona.respond_chain | ChatOpenAI(
            model="gpt-3.5-turbo",
        ) | StrOutputParser() | self.persona.postprocess_chain
        self.chat_history = []
        self._lock = Lock()

    def respond(self, user_msg) -> Generator[Dict, None, None]:
        def format_response(content, partial=False):
            # format response from openai chat to be sent to the user
            formatted_response = {
                "text": content,
                "commands": [],
                "partial": partial
            }
            return formatted_response

        with self._lock:
            chat_history_formated = ""
            for llm_res in self.chat_history:
                if isinstance(llm_res, HumanMessage):
                    chat_history_formated += f'User Statement: {llm_res.content}\n'
                elif isinstance(llm_res, AIMessage):
                    chat_history_formated += f'{self.assistant_name} Statement: {llm_res.content}\n'
                else:
                    raise Exception(f'{llm_res} is not supported nor expected!')

            self.chat_history.append(HumanMessage(content=user_msg))
            ai_msg_stream = self.conversational_qa_chain.stream(
                self.persona.construct_input(user_msg, chat_history_formated)
            )
            ai_res_content = ""
            for chunk in ai_msg_stream:
                ai_res_content += chunk
                if chunk == "":
                    continue
                # TODO append to ai message internally
                yield format_response(chunk, partial=True)
            yield format_response(ai_res_content)
            self.chat_history.append(AIMessage(content=ai_res_content))



    def process_procedures_if_on(self):
        # TODO: Implement
        pass
