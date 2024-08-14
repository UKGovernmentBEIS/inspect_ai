import json


def get_task_details(task_name, challenges_path, task_info_path):
    try:
        with open(challenges_path, "r") as file:
            tasks = json.load(file)
            task_info = tasks.get(task_name)
            if task_info:
                objective_prompt = task_info["objective_prompt"]
                flag = task_info["flag"]
            else:
                print("Task {task_name} information does not exist.")
    except Exception as e:
        print(f"Error: {e}")

    try:
        with open(task_info_path, "r") as file:
            info = json.load(file)
            address = info.get("address")
    except Exception as e:
        print(f"Error: {e}")

    return objective_prompt, flag, address


def create_system_message_file(
    address, objective_prompt, template_file_path, output_file_path
):
    try:
        with open(template_file_path, "r") as file:
            content = file.read()
        content = content.replace("{TARGET_ADDR}", address)
        content = content.replace("{OBJECTIVE_PROMPT}", objective_prompt)
        print(objective_prompt)
        with open(output_file_path, "w") as file:
            file.write(content)
    except Exception as e:
        print(f"Error: {e}")
