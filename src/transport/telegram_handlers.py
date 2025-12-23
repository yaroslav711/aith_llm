import json
import logging
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes

from src.agents.graph import process_message
from src.transport.session_manager import SessionManager

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """Telegram bot handlers for duo mediation."""
    
    def __init__(self, session_manager: SessionManager, bot_username: str):
        self.session_manager = session_manager
        self.bot_username = bot_username
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # Check if there's an invite code in args
        invite_code = context.args[0] if context.args else None
        
        logger.info(f"START command from user {user_id} (@{username}), invite_code: {invite_code}")
        
        if invite_code:
            # User is joining via invite
            await self._handle_invite_join(update, invite_code, user_id)
        else:
            # User is starting fresh - create partnership and wait for partner
            await self._handle_user_start(update, user_id)
    
    async def invite_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /invite command - generate invite link."""
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Check if user already has a complete partnership
        if self.session_manager.is_partnership_complete(user_id):
            await update.message.reply_text(
                "У вас уже есть активное партнерство.\n\n"
                "Вы можете сразу начать разговор — просто напишите мне сообщение."
            )
            return
        
        # Get or create partnership
        partnership = self.session_manager.get_partnership(user_id)
        if not partnership:
            partnership = self.session_manager.create_partnership(user_id)
        
        # Generate invite URL
        if partnership.invite_code:
            invite_url = f"https://t.me/{self.bot_username}?start={partnership.invite_code}"
            
            message = (
                "Отлично, ваша ссылка готова!\n\n"
                f"{invite_url}\n\n"
                "Отправьте её своему партнеру — как только он перейдет по ссылке, мы сможем начать разговор.\n"
                "🕑 Ссылка активна 3 часа"
            )
            await update.message.reply_text(message)
        else:
            # Partnership already complete
            await update.message.reply_text(
                "У вас уже есть активное партнерство.\n"
                "Просто отправьте сообщение, чтобы начать медиационную сессию."
            )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = (
            "📖 Доступные команды:\n\n"
            "/start — Начать работу с ботом\n\n"
            "/invite — Создать приглашение для партнера\n"
            "Отправьте полученную ссылку партнеру для создания пары\n\n"
            "/help — Показать эту справку\n\n"
            "💬 После создания партнерства просто отправьте сообщение для начала медиации."
        )
        await update.message.reply_text(help_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages from users."""
        if not update.effective_user or not update.message or not update.message.text:
            return
        
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Check if partnership is complete
        if not self.session_manager.is_partnership_complete(user_id):
            await update.message.reply_text(
                "Для начала медиации необходимо создать партнерство.\n\n"
                "Используйте команду /invite для создания ссылки-приглашения и отправьте её партнеру."
            )
            return
        
        # Show typing indicator
        try:
            await context.bot.send_chat_action(chat_id=user_id, action="typing")
        except Exception as e:
            logger.debug(f"Failed to send typing action: {e}")
        
        # Get partnership and session
        partnership = self.session_manager.get_partnership(user_id)
        if not partnership:
            await update.message.reply_text(
                "Ошибка: партнерство не найдено. Используйте /start для начала."
            )
            return
        
        session = self.session_manager.get_or_create_session(partnership.partnership_id)
        
        # Determine user role (user_1 or user_2)
        user_role = "user_1" if partnership.user1_id == user_id else "user_2"
        
        # Add user message to session
        user_message = f"[{user_role}]: {message_text}"
        self.session_manager.add_message(partnership.partnership_id, "user", user_message)
        
        try:
            # Process through LangGraph
            result = await process_message(
                session_id=session.session_id,
                messages=session.messages,
                current_agent=session.current_agent,
                classification=session.classification,
            )
            
            response_data = result.get("response")
            
            # Update session state
            if result.get("current_agent"):
                self.session_manager.update_session(
                    partnership.partnership_id,
                    current_agent=result["current_agent"]
                )
            
            if result.get("classification"):
                self.session_manager.update_session(
                    partnership.partnership_id,
                    classification=result["classification"]
                )
            
            # Add assistant response to session
            if response_data:
                self.session_manager.add_message(
                    partnership.partnership_id,
                    "assistant",
                    json.dumps(response_data, ensure_ascii=False)
                )
            
            # Parse and send responses to recipients
            if response_data and "messages" in response_data:
                for msg in response_data["messages"]:
                    recipient = msg.get("recipient", "user_1")
                    text = msg.get("text", "")
                    
                    # Determine recipient user_id
                    if recipient == "user_1":
                        recipient_id = partnership.user1_id
                    else:
                        recipient_id = partnership.user2_id
                    
                    if text and recipient_id:
                        try:
                            await context.bot.send_message(
                                chat_id=recipient_id,
                                text=text
                            )
                            logger.info(f"Delivered message to {recipient} (user_id={recipient_id})")
                        except Exception as e:
                            logger.error(f"Failed to deliver message to {recipient_id}: {e}")
        
        except Exception as exc:
            import traceback
            logger.error(f"Error processing message: {exc}")
            traceback.print_exc()
            
            # User-friendly error message
            error_msg = (
                "Упс, что-то пошло не так при обработке вашего сообщения 🤖\n\n"
                "Пожалуйста, попробуйте снова через пару минут."
            )
            
            # If it's an OpenAI API error, provide more specific message
            if "openai" in str(type(exc)).lower() or "permission" in str(exc).lower():
                error_msg = (
                    "Произошла ошибка при обращении к AI-сервису.\n\n"
                    "Пожалуйста, попробуйте снова через пару минут."
                )
            
            await update.message.reply_text(error_msg)
    
    async def _handle_user_start(self, update: Update, user_id: int):
        """Handle user starting without invite - create partnership."""
        # Check if user already has partnership
        partnership = self.session_manager.get_partnership(user_id)
        
        if partnership:
            if partnership.user2_id is not None:
                # Partnership complete
                message = (
                    "Добро пожаловать!\n\n"
                    "У вас уже есть активное партнерство.\n"
                    "Просто отправьте сообщение, чтобы начать медиационную сессию."
                )
            else:
                # Partnership incomplete - regenerate invite
                partnership = self.session_manager.create_partnership(user_id)
                invite_url = f"https://t.me/{self.bot_username}?start={partnership.invite_code}"
                
                message = (
                    "Привет! Я AI Mediator 🕊️\n\n"
                    "Я помогаю парам находить решения в конфликтных ситуациях.\n\n"
                    "Как это работает:\n"
                    "• Каждый из вас общается со мной в своем чате\n"
                    "• Я слушаю обе стороны и помогаю найти компромисс\n\n"
                    "Ваша ссылка-приглашение готова:\n"
                    f"{invite_url}\n\n"
                    "Отправьте её своему партнеру, и мы сможем начать 🤍"
                )
        else:
            # Create new partnership
            partnership = self.session_manager.create_partnership(user_id)
            invite_url = f"https://t.me/{self.bot_username}?start={partnership.invite_code}"
            
            message = (
                "Привет! Я AI Mediator 🕊️\n\n"
                "Я помогаю парам находить решения в конфликтных ситуациях.\n\n"
                "Как это работает:\n"
                "• Каждый из вас общается со мной в своем чате\n"
                "• Я слушаю обе стороны и помогаю найти компромисс\n\n"
                "Ваша ссылка-приглашение готова:\n"
                f"{invite_url}\n\n"
                "Отправьте её своему партнеру, и мы сможем начать 🤍"
            )
        
        await update.message.reply_text(message)
    
    async def _handle_invite_join(self, update: Update, invite_code: str, user_id: int):
        """Handle user joining via invite code."""
        # Get partnership by invite
        partnership = self.session_manager.get_partnership_by_invite(invite_code)
        
        if not partnership:
            await update.message.reply_text(
                "Приглашение не найдено или истекло ⏰\n\n"
                "Попросите партнера создать новое через /invite"
            )
            return
        
        # Check if user is trying to accept their own invite
        if partnership.user1_id == user_id:
            await update.message.reply_text(
                "Вы не можете принять свое собственное приглашение 😊\n\n"
                "Отправьте эту ссылку партнеру, чтобы он мог присоединиться."
            )
            return
        
        # Check if user already has a partnership
        existing_partnership = self.session_manager.get_partnership(user_id)
        if existing_partnership:
            await update.message.reply_text(
                "У вас уже есть активное партнерство.\n\n"
                "Вы можете сразу начать разговор — просто напишите мне сообщение."
            )
            return
        
        # Accept invite
        partnership = self.session_manager.accept_invite(invite_code, user_id)
        
        if partnership:
            # Send welcome message to user_2 (joiner)
            joiner_message = (
                "Привет! Я AI Mediator 🕊️\n\n"
                "Ваш партнер пригласил вас для совместного разговора со мной.\n\n"
                "Как это работает:\n"
                "• Каждый общается со мной в своем чате\n"
                "• Я слушаю обе стороны и помогаю найти решение, которое устроит вас обоих\n\n"
                "Когда будете готовы, просто напишите мне — и мы начнем 🤍"
            )
            await update.message.reply_text(joiner_message)
            
            # Notify user_1 (creator) that partner joined
            creator_message = (
                "Ваш партнер присоединился! 🤝\n\n"
                "Теперь вы можете общаться вместе — каждый в своем чате.\n"
                "Я буду помогать вам понять друг друга и найти решение, которое устроит обоих 🤍"
            )
            
            try:
                await update.get_bot().send_message(
                    chat_id=partnership.user1_id,
                    text=creator_message
                )
            except Exception as e:
                logger.error(f"Failed to notify creator {partnership.user1_id}: {e}")
        else:
            await update.message.reply_text(
                "Не удалось принять приглашение. Попробуйте снова или попросите партнера создать новое."
            )

