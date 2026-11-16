from agent import Agent
from config import config, logger
import sys
import os

def main():
    try:
        # Validate configuration
        config.validate()
        model_path = config.MODEL_PATH
        
        logger.info(f"Agent is using {os.path.basename(model_path)}")
        agent = Agent(model_path)
        
        logger.info("Generating meal plan...")
        meal_plan = agent.generate_meal_plan()
        
        if not meal_plan:
            logger.warning("No meal plan generated")
            return
        
        logger.info("Generating shopping list...")
        shopping_list = agent.generate_shopping_list(meal_plan)
        
        print(f"\nThe shopping list is:")
        for item in shopping_list:
            print(f"  - {item}")
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        sys.exit(1)
    
if __name__ == "__main__":
    main()