import glob
import logging
import os
import platform

import cv2
import mxnet as mx
import mxnet.gluon as gluon
from tqdm import tqdm

from core import Prediction
from core import box_resize
from core import plot_bbox, export_block_for_cplusplus
from core import testdataloader

logfilepath = ""  # 따로 지정하지 않으면 terminal에 뜸
if os.path.isfile(logfilepath):
    os.remove(logfilepath)
logging.basicConfig(filename=logfilepath, level=logging.INFO)


def run(video_list=True,
        video_path="",
        weight_path="weights",
        load_name="512_512_ADAM_PEFF_0",
        load_period=100,
        decode_number=5000,
        multiperclass=True,
        nms_thresh=0.5,
        nms_topk=500,
        except_class_thresh=0.05,
        plot_class_thresh=0.5,
        video_save_path="result_video",
        video_show=True,
        video_save=True):
    if video_save:
        if not os.path.exists(video_save_path):
            os.makedirs(video_save_path)

    if mx.context.num_gpus() > 0:
        GPU_COUNT = mx.context.num_gpus()
    else:
        GPU_COUNT = 0

    if GPU_COUNT <= 0:
        ctx = mx.cpu(0)
    elif GPU_COUNT > 0:
        ctx = mx.gpu(0)

    # 운영체제 확인
    if platform.system() == "Linux":
        logging.info(f"{platform.system()} OS")
    elif platform.system() == "Windows":
        logging.info(f"{platform.system()} OS")
    else:
        logging.info(f"{platform.system()} OS")

    if GPU_COUNT > 0:
        free_memory, total_memory = mx.context.gpu_memory_info(0)
        free_memory = round(free_memory / (1024 * 1024 * 1024), 2)
        total_memory = round(total_memory / (1024 * 1024 * 1024), 2)
        logging.info(f'Running on {ctx} / free memory : {free_memory}GB / total memory {total_memory}GB')
    else:
        logging.info(f'Running on {ctx}')

    logging.info(f"test {load_name}")
    netheight = int(load_name.split("_")[0])
    netwidth = int(load_name.split("_")[1])
    if not isinstance(netheight, int) and not isinstance(netwidth, int):
        logging.info("height is not int")
        logging.info("width is not int")
        raise ValueError
    else:
        logging.info(f"network input size : {(netheight, netwidth)}")

    _, test_dataset = testdataloader()

    weight_path = os.path.join(weight_path, load_name)
    sym = os.path.join(weight_path, f'{load_name}-symbol.json')
    params = os.path.join(weight_path, f'{load_name}-{load_period:04d}.params')

    logging.info("symbol model test")
    if os.path.exists(sym) and os.path.exists(params):
        logging.info(f"loading {os.path.basename(params)} weights\n")
        net = gluon.SymbolBlock.imports(sym,
                                        ['data'],
                                        params, ctx=ctx)
    else:
        raise FileExistsError

    try:
        net = export_block_for_cplusplus(block=net,
                                         data_shape=tuple((netheight, netwidth)) + tuple((3,)),
                                         preprocess=True,  # c++ 에서 inference시 opencv에서 읽은 이미지 그대로 넣으면 됨
                                         layout='HWC',
                                         ctx=ctx)
    except Exception as E:
        logging.error(f"adding preprocessing layer 실패 : {E}")
    else:
        logging.info(f"adding preprocessing layer 성공 ")

    net.hybridize(active=True, static_alloc=True, static_shape=True)

    # BoxEncoder, BoxDecoder 에서 같은 값을 가져야함
    prediction = Prediction(
        from_sigmoid=False,
        num_classes=test_dataset.num_class,
        decode_number=decode_number,
        nms_thresh=nms_thresh,
        nms_topk=nms_topk,
        except_class_thresh=except_class_thresh,
        multiperclass=multiperclass)

    fourcc = cv2.VideoWriter_fourcc(*'DIVX')
    if video_list:
        types = ('*.mp4', '*.avi')
        videos_path = []
        for type in types:
            videos_path.extend(glob.glob(os.path.join(video_path, type)))
        if videos_path:
            for v_path in tqdm(videos_path):
                cap = cv2.VideoCapture(v_path)
                nframe = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                name = os.path.splitext(os.path.basename(v_path))[0]
                out = cv2.VideoWriter(os.path.join(video_save_path, f'{name}.avi'), fourcc, fps, (width, height))
                logging.info(f"real input size : {(height, width)}")
                # while(cap.isOpened()):
                for _ in tqdm(range(0, nframe)):
                    ret, image = cap.read()
                    if ret:
                        origin_image = image.copy()
                        image = cv2.resize(image, (netwidth, netheight), interpolation=3)
                        image[:, :, (0, 1, 2)] = image[:, :, (2, 1, 0)]  # BGR to RGB
                        image = mx.nd.array(image, ctx=ctx)
                        image = image.expand_dims(axis=0)

                        cls_preds, box_preds, anchors = net(image)
                        ids, scores, bboxes = prediction(cls_preds, box_preds, anchors)

                        bbox = box_resize(bboxes[0], (netwidth, netheight), (width, height))
                        result = plot_bbox(origin_image, bbox, scores=scores[0], labels=ids[0],
                                           thresh=plot_class_thresh,
                                           reverse_rgb=False,
                                           class_names=test_dataset.classes)
                        if video_save:
                            out.write(result)
                        if video_show:
                            cv2.imshow(name, result)
                            cv2.waitKey(1)

                cap.release()
                out.release()
                cv2.destroyAllWindows()

        else:
            raise FileNotFoundError
    else:
        cap = cv2.VideoCapture(video_path)
        nframe = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        name = os.path.splitext(os.path.basename(video_path))[0]
        out = cv2.VideoWriter(os.path.join(video_save_path, f'{name}.avi'), fourcc, fps, (width, height))
        logging.info(f"real input size : {(height, width)}")

        # while(cap.isOpened()):
        for _ in tqdm(range(0, nframe)):
            ret, image = cap.read()
            if ret:

                origin_image = image.copy()
                image = cv2.resize(image, (netwidth, netheight), interpolation=3)
                image[:, :, (0, 1, 2)] = image[:, :, (2, 1, 0)]  # BGR to RGB
                image = mx.nd.array(image, ctx=ctx)
                image = image.expand_dims(axis=0)

                cls_preds, box_preds, anchors = net(image)
                ids, scores, bboxes = prediction(cls_preds, box_preds, anchors)

                bbox = box_resize(bboxes[0], (netwidth, netheight), (width, height))
                result = plot_bbox(origin_image, bbox, scores=scores[0], labels=ids[0],
                                   thresh=plot_class_thresh,
                                   reverse_rgb=False,
                                   class_names=test_dataset.classes)

                if video_save:
                    out.write(result)
                if video_show:
                    cv2.imshow(name, result)
                    cv2.waitKey(1)

        cap.release()
        out.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run(video_list=True,  # True일 때, 폴더에 있는 비디오(mp4)들 전부다 평가 / False일 때, 비디오 한개 평가
        # video_path='test_video/C050105_001.mp4',
        video_path='test_video',
        weight_path="weights",
        load_name="512_512_ADAM_PEFF_0",
        load_period=100,
        decode_number=5000,
        multiperclass=True,
        nms_thresh=0.5,
        nms_topk=500,
        except_class_thresh=0.05,
        plot_class_thresh=0.5,
        video_save_path="result_video",
        video_show=True,
        video_save=True)
